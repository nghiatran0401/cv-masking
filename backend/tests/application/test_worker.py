"""Stage 12: the worker service and loop, driven in-process with stub pipelines.

The real worker process is covered in test_worker_process.py; here the
processor runs the stub in this process so every outcome, race, and storage
failure can be staged exactly.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
import worker_stubs as stubs
from service_helpers import ManualClock, uploaded_document

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.application import JobService, WorkerLoop, WorkerService
from cv_masking.domain.batch import Batch, BatchState
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.ids import BatchId
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.ports.processing import (
    ProcessingCrashedError,
    ProcessingReport,
    ProcessingStoppedError,
    ProcessingTimeoutError,
    ValidationReport,
    VerificationReport,
)
from cv_masking.ports.storage import (
    Producer,
    StorageError,
    StoredObject,
    SweepReport,
)

type Hook = Callable[[], None]


class _Session:
    def __init__(self, owner: "_InProcess") -> None:
        self._owner = owner

    def _before(self, op: str) -> None:
        hook = self._owner.hooks.get(op)
        if hook is not None:
            hook()
        error = self._owner.errors.get(op)
        if error is not None:
            raise error

    def validate(self, source: StoredObject) -> ValidationReport:
        self._before("validate")
        return self._owner.pipeline.validate(source)

    def process(self, policy: MaskingPolicy) -> ProcessingReport:
        self._before("process")
        return self._owner.pipeline.process(policy)

    def verify(self, output: StoredObject) -> VerificationReport:
        self._before("verify")
        return self._owner.pipeline.verify(output)


class _InProcess:
    """A DocumentProcessor that runs the stub pipeline here, with staged errors and hooks."""

    def __init__(self, root: StorageRoot) -> None:
        self.pipeline = stubs.StubPipeline(root.path)
        self.errors: dict[str, Exception] = {}
        self.hooks: dict[str, Hook] = {}
        self.sessions = 0
        self.refuse_start = False
        self.closed = False

    @contextmanager
    def session(self) -> Iterator[_Session]:
        if self.refuse_start:
            raise ProcessingCrashedError
        self.sessions += 1
        try:
            yield _Session(self)
        finally:
            self.pipeline.forget()

    def close(self) -> None:
        self.closed = True


class _CountingSweeper:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    def sweep(self, now: datetime) -> SweepReport:
        self.calls += 1
        if self._fail:
            raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)
        return SweepReport()


class _FullOutputStore(LocalOutputStore):
    def save(
        self, document_format: DocumentFormat, producer: Producer, *, max_bytes: int
    ) -> StoredObject:
        raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)


@pytest.fixture
def processor(root: StorageRoot) -> _InProcess:
    return _InProcess(root)


@pytest.fixture
def worker(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    processor: _InProcess,
    clock: ManualClock,
) -> WorkerService:
    return WorkerService(service, input_store, output_store, processor, clock)


def _objects(root: StorageRoot, kind: str) -> list[Path]:
    return sorted((root.path / kind).iterdir())


def _running_batch(
    service: JobService, input_store: LocalInputStore, clock: ManualClock, *contents: bytes
) -> tuple[Batch, list[DocumentJob]]:
    """Each document is one clock step newer than the last, so queue order is upload order."""
    batch = service.create_batch()
    jobs = []
    for content in contents:
        clock.advance()
        jobs.append(uploaded_document(service, input_store, batch.batch_id, content=content))
    started = service.start_batch(
        batch.batch_id, expected_version=service.get_batch(batch.batch_id).version
    )
    return started, jobs


def _drain(worker: WorkerService) -> int:
    runs = 0
    while worker.run_next():
        runs += 1
    return runs


def _states(service: JobService, batch_id: BatchId) -> list[DocumentState]:
    return [job.state for job in service.list_documents(batch_id)]


# ------------------------------------------------------------------ outcomes


def test_a_document_completes_with_the_output_the_worker_returned(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    worker: WorkerService,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    batch, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    done = worker.run(job.document_id)
    assert done is not None
    assert done.state is DocumentState.COMPLETED
    assert done.attempt == 1
    assert done.verification is not None
    assert done.verification.verifier_id == stubs.STUB_VERIFIER_ID
    assert done.output_ref is not None
    with output_store.open(done.output_ref, DocumentFormat.PDF) as handle:
        assert handle.read() == stubs.stub_output(stubs.LIGHT)
    assert _objects(root, "inputs") == []
    assert service.get_batch(batch.batch_id).state is BatchState.FINISHED


@pytest.mark.parametrize(
    ("content", "state", "code", "reasons"),
    [
        (stubs.MALFORMED, DocumentState.FAILED, ErrorCode.PDF_MALFORMED, frozenset()),
        (
            stubs.BLOCKED,
            DocumentState.REVIEW_REQUIRED,
            None,
            frozenset({ReviewReason.PDF_ENCRYPTED}),
        ),
        (
            stubs.REVIEW,
            DocumentState.REVIEW_REQUIRED,
            None,
            frozenset({ReviewReason.DETECT_LOW_CONFIDENCE}),
        ),
    ],
    ids=["malformed", "blocked", "findings-review"],
)
def test_each_pipeline_outcome_settles_the_document(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    content: bytes,
    state: DocumentState,
    code: ErrorCode | None,
    reasons: frozenset[ReviewReason],
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, content)
    done = worker.run(job.document_id)
    assert done is not None
    assert done.state is state
    assert done.error_code is code
    assert done.review_reasons == reasons


def test_a_findings_review_can_be_kept_and_a_blocked_one_only_deleted(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    _, (review, blocked) = _running_batch(service, input_store, clock, stubs.REVIEW, stubs.BLOCKED)
    _drain(worker)
    held = service.get_document(review.document_id)
    assert held.can_approve_review
    kept = service.approve_review(held.document_id, expected_version=held.version)
    assert kept.state is DocumentState.COMPLETED
    assert kept.findings_review_approved
    stuck = service.get_document(blocked.document_id)
    assert not stuck.can_approve_review
    with pytest.raises(InvalidTransitionError):
        service.approve_review(stuck.document_id, expected_version=stuck.version)
    denied = service.deny_review(stuck.document_id, expected_version=stuck.version)
    assert denied.state is DocumentState.REJECTED
    assert len(_objects(root, "outputs")) == 1


def test_denying_a_findings_review_deletes_the_output(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.REVIEW)
    held = worker.run(job.document_id)
    assert held is not None
    assert len(_objects(root, "outputs")) == 1
    denied = service.deny_review(held.document_id, expected_version=held.version)
    assert denied.state is DocumentState.REJECTED
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == []


def test_hidden_content_is_recorded_by_kind_and_count(
    service: JobService, input_store: LocalInputStore, worker: WorkerService, clock: ManualClock
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.HIDDEN)
    worker.run(job.document_id)
    stored = service.get_document(job.document_id)
    assert stored.state is DocumentState.COMPLETED
    assert stored.hidden_removed.as_dict() == {HiddenContentCategory.ANNOTATIONS: 2}


def test_one_malformed_file_does_not_fail_the_batch(
    service: JobService, input_store: LocalInputStore, worker: WorkerService, clock: ManualClock
) -> None:
    batch, _ = _running_batch(
        service, input_store, clock, stubs.LIGHT, stubs.MALFORMED, stubs.LIGHT + b"2"
    )
    assert _drain(worker) == 3
    assert _states(service, batch.batch_id) == [
        DocumentState.COMPLETED,
        DocumentState.FAILED,
        DocumentState.COMPLETED,
    ]
    assert service.get_batch(batch.batch_id).state is BatchState.FINISHED


def test_an_unexpected_error_fails_only_that_document(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    _, (first, second) = _running_batch(
        service, input_store, clock, stubs.LIGHT, stubs.LIGHT + b"2"
    )
    processor.errors["process"] = RuntimeError("synthetic bug")
    failed = worker.run(first.document_id)
    assert failed is not None
    assert failed.state is DocumentState.FAILED
    assert failed.error_code is ErrorCode.INTERNAL_ERROR
    processor.errors.clear()
    done = worker.run(second.document_id)
    assert done is not None
    assert done.state is DocumentState.COMPLETED
    assert len(_objects(root, "outputs")) == 1


@pytest.mark.parametrize("op", ["validate", "process", "verify"])
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProcessingTimeoutError(), ErrorCode.JOB_TIMEOUT),
        (ProcessingCrashedError(), ErrorCode.INTERNAL_ERROR),
        (ProcessingStoppedError(), ErrorCode.JOB_INTERRUPTED),
    ],
    ids=["timeout", "crash", "shutdown"],
)
def test_a_worker_that_stops_answering_fails_the_document_and_leaves_no_output(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    root: StorageRoot,
    op: str,
    error: Exception,
    code: ErrorCode,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    processor.errors[op] = error
    done = worker.run(job.document_id)
    assert done is not None
    assert done.state is DocumentState.FAILED
    assert done.error_code is code
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == []


def test_a_worker_that_cannot_start_leaves_the_document_waiting(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    processor.refuse_start = True
    with pytest.raises(ProcessingCrashedError):
        worker.run(job.document_id)
    assert service.get_document(job.document_id).state is DocumentState.UPLOADED
    processor.refuse_start = False
    done = worker.run(job.document_id)
    assert done is not None
    assert done.state is DocumentState.COMPLETED


# ------------------------------------------------------------------ storage


def test_an_output_that_cannot_be_stored_fails_the_document(
    service: JobService,
    input_store: LocalInputStore,
    processor: _InProcess,
    clock: ManualClock,
    root: StorageRoot,
) -> None:
    worker = WorkerService(service, input_store, _FullOutputStore(root), processor, clock)
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    done = worker.run(job.document_id)
    assert done is not None
    assert done.error_code is ErrorCode.REDACT_OUTPUT_WRITE_FAILED
    assert _objects(root, "outputs") == []


def test_an_input_changed_during_processing_deletes_the_output(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)

    def tamper() -> None:
        (path,) = _objects(root, "inputs")
        path.chmod(0o600)
        path.write_bytes(stubs.LIGHT + b"tampered\n")

    processor.hooks["process"] = tamper
    done = worker.run(job.document_id)
    assert done is not None
    assert done.error_code is ErrorCode.STORAGE_INTEGRITY_FAILED
    assert _objects(root, "outputs") == []


def test_maintenance_sweeps_and_reconciles_and_survives_storage_errors(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    sweeper = _CountingSweeper(fail=True)
    worker = WorkerService(service, input_store, output_store, processor, clock, sweeper)
    worker.maintain()
    assert sweeper.calls == 1


# ------------------------------------------------------------------ queue order and delivery


def test_the_oldest_running_batch_is_served_first(
    service: JobService, input_store: LocalInputStore, worker: WorkerService, clock: ManualClock
) -> None:
    first, _ = _running_batch(service, input_store, clock, stubs.LIGHT, stubs.LIGHT + b"2")
    clock.advance()
    second, _ = _running_batch(service, input_store, clock, stubs.LIGHT + b"3")
    clock.advance()
    open_batch = service.create_batch()
    waiting = uploaded_document(service, input_store, open_batch.batch_id, content=stubs.LIGHT)
    order: list[BatchId] = []
    while (document_id := worker.next_document()) is not None:
        order.append(service.get_document(document_id).batch_id)
        worker.run(document_id)
    assert order == [first.batch_id, first.batch_id, second.batch_id]
    assert service.get_document(waiting.document_id).state is DocumentState.UPLOADED
    assert worker.run(waiting.document_id) is None


def test_duplicate_delivery_processes_the_document_once(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    first = worker.run(job.document_id)
    again = worker.run(job.document_id)
    assert first is not None
    assert again is None
    assert service.get_document(job.document_id) == first
    assert len(_objects(root, "outputs")) == 1


def test_concurrent_duplicate_delivery_processes_the_document_once(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    start = threading.Barrier(2)
    workers = [
        WorkerService(service, input_store, output_store, _InProcess(root), clock) for _ in range(2)
    ]
    results: list[DocumentJob | None] = []

    def deliver(worker: WorkerService) -> None:
        start.wait()
        results.append(worker.run(job.document_id))

    threads = [threading.Thread(target=deliver, args=(w,)) for w in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(result is None for result in results) == [False, True]
    assert service.get_document(job.document_id).state is DocumentState.COMPLETED
    assert len(_objects(root, "outputs")) == 1


def test_repeated_runs_of_the_same_file_give_the_same_output(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    worker: WorkerService,
    clock: ManualClock,
) -> None:
    _, jobs = _running_batch(service, input_store, clock, stubs.LIGHT)
    _, again = _running_batch(service, input_store, clock, stubs.LIGHT)
    _drain(worker)
    outputs = []
    for job in (*jobs, *again):
        done = service.get_document(job.document_id)
        assert done.output_ref is not None
        with output_store.open(done.output_ref, DocumentFormat.PDF) as handle:
            outputs.append(handle.read())
    assert outputs[0] == outputs[1]


# ------------------------------------------------------------------ cancel, purge, recovery


def test_a_cancelled_document_is_never_processed(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    service.cancel_document(job.document_id)
    assert worker.run(job.document_id) is None
    assert worker.next_document() is None
    assert service.get_document(job.document_id).state is DocumentState.CANCELLED


def test_a_document_being_processed_cannot_be_cancelled(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    refused: list[bool] = []

    def cancel() -> None:
        with pytest.raises(InvalidTransitionError):
            service.cancel_document(job.document_id)
        refused.append(True)

    processor.hooks["process"] = cancel
    done = worker.run(job.document_id)
    assert refused == [True]
    assert done is not None
    assert done.state is DocumentState.COMPLETED


@pytest.mark.parametrize("op", ["validate", "process", "verify"])
def test_a_batch_purged_during_processing_leaves_no_files(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    root: StorageRoot,
    op: str,
    clock: ManualClock,
) -> None:
    batch, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    processor.hooks[op] = lambda: service.purge_batch(batch.batch_id)
    assert worker.run(job.document_id) is None
    assert service.list_batches() == ()
    service.reconcile_storage()
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == []


def test_recovery_fails_documents_a_previous_run_left_in_progress(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    root: StorageRoot,
    clock: ManualClock,
) -> None:
    batch, (validating, processing, waiting) = _running_batch(
        service, input_store, clock, stubs.LIGHT, stubs.LIGHT + b"2", stubs.LIGHT + b"3"
    )
    service.apply(validating.document_id, lambda j, at: j.start_validation(at))
    service.apply(processing.document_id, lambda j, at: j.start_validation(at))
    service.apply(processing.document_id, lambda j, at: j.validation_passed(at))
    service.apply(processing.document_id, lambda j, at: j.start_processing(MaskingPolicy(), at))
    assert worker.recover() == 2
    for job in (validating, processing):
        stored = service.get_document(job.document_id)
        assert stored.state is DocumentState.FAILED
        assert stored.error_code is ErrorCode.JOB_INTERRUPTED
    assert service.get_document(waiting.document_id).state is DocumentState.UPLOADED
    assert worker.recover() == 0
    _drain(worker)
    assert service.get_batch(batch.batch_id).state is BatchState.FINISHED
    assert len(_objects(root, "inputs")) == 0


# ------------------------------------------------------------------ loop


def _wait_for(predicate: Callable[[], bool], seconds: float = 10.0) -> bool:
    event = threading.Event()
    for _ in range(int(seconds / 0.02)):
        if predicate():
            return True
        event.wait(0.02)
    return predicate()


def test_the_loop_recovers_cleans_and_processes_notified_batches(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    sweeper = _CountingSweeper()
    worker = WorkerService(service, input_store, output_store, processor, clock, sweeper)
    batch, (held, _) = _running_batch(service, input_store, clock, stubs.LIGHT, stubs.LIGHT + b"2")
    service.apply(held.document_id, lambda j, at: j.start_validation(at))
    loop = WorkerLoop(worker, processor, idle_seconds=30)
    loop.start()
    try:
        assert sweeper.calls == 1
        assert service.get_document(held.document_id).error_code is ErrorCode.JOB_INTERRUPTED
        assert _wait_for(lambda: service.get_batch(batch.batch_id).state is BatchState.FINISHED)
        _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT + b"3")
        loop.notify()
        assert _wait_for(
            lambda: service.get_document(job.document_id).state is DocumentState.COMPLETED, 5
        )
    finally:
        loop.stop()
    assert not loop.running
    assert processor.closed
    with pytest.raises(RuntimeError):
        loop.start()


def test_the_loop_runs_maintenance_on_its_interval(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    sweeper = _CountingSweeper()
    worker = WorkerService(service, input_store, output_store, processor, clock, sweeper)
    ticks = iter(range(0, 10_000, 400))
    loop = WorkerLoop(
        worker,
        processor,
        idle_seconds=0.01,
        maintenance_interval_seconds=600,
        monotonic=lambda: float(next(ticks, 10_000)),
    )
    loop.start()
    try:
        assert _wait_for(lambda: sweeper.calls >= 3)
    finally:
        loop.stop()


def test_the_loop_survives_a_worker_that_cannot_start(
    service: JobService,
    input_store: LocalInputStore,
    worker: WorkerService,
    processor: _InProcess,
    clock: ManualClock,
) -> None:
    _, (job,) = _running_batch(service, input_store, clock, stubs.LIGHT)
    processor.refuse_start = True
    loop = WorkerLoop(worker, processor, idle_seconds=0.01)
    loop.start()
    try:
        threading.Event().wait(0.1)
        assert loop.running
        assert service.get_document(job.document_id).state is DocumentState.UPLOADED
        processor.refuse_start = False
        assert _wait_for(
            lambda: service.get_document(job.document_id).state is DocumentState.COMPLETED
        )
    finally:
        loop.stop()
