"""Stage 12: the real worker process (spawn, one process, pipe) under load and failure.

Stub pipelines come from worker_stubs (imported by name inside the worker);
the end-to-end cases run the production pipeline on synthetic fixtures.
"""

import time
from collections.abc import Callable, Iterator

import pytest
import synthetic_docx_redaction as docx_fixture
import worker_stubs as stubs
from fastapi.testclient import TestClient
from service_helpers import ManualClock, uploaded_document

# Load pymupdf via this helper first (see test_extract.py).
from synthetic_redaction import cv_pdf, with_hidden

from cv_masking.adapters.local_storage import (
    LocalInputStore,
    LocalOutputStore,
    LocalStorageSweeper,
    StorageRoot,
)
from cv_masking.adapters.worker import PipelineFactory, SubprocessProcessor
from cv_masking.api.app import create_app
from cv_masking.api.runtime import Runtime, build_pipeline
from cv_masking.application import JobService, UploadService, WorkerLoop, WorkerService
from cv_masking.config import Settings
from cv_masking.domain.batch import Batch, BatchState
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.verification import VerificationOutcome
from cv_masking.ports.processing import ProcessingCrashedError

_STUB_TIMEOUT_SECONDS = 20.0


@pytest.fixture
def make_processor(root: StorageRoot) -> Iterator[Callable[..., SubprocessProcessor]]:
    made: list[SubprocessProcessor] = []

    def make(
        factory: PipelineFactory = stubs.stub_pipeline,
        timeout_seconds: float = _STUB_TIMEOUT_SECONDS,
    ) -> SubprocessProcessor:
        processor = SubprocessProcessor(factory, root.path, timeout_seconds=timeout_seconds)
        made.append(processor)
        return processor

    yield make
    for processor in made:
        processor.close()


def _worker(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    processor: SubprocessProcessor,
    clock: ManualClock,
    root: StorageRoot,
) -> WorkerService:
    return WorkerService(
        service, input_store, output_store, processor, clock, LocalStorageSweeper(root)
    )


def _running_batch(
    service: JobService,
    input_store: LocalInputStore,
    clock: ManualClock,
    contents: list[bytes],
    fmt: DocumentFormat = DocumentFormat.PDF,
) -> tuple[Batch, list[DocumentJob]]:
    """Each document is one clock step newer than the last, so queue order is upload order."""
    batch = service.create_batch()
    jobs = []
    for content in contents:
        clock.advance()
        job = service.add_document(batch.batch_id)
        stored = input_store.save_stream(fmt, [content], max_bytes=HARD_MAX_FILE_BYTES)
        jobs.append(service.record_upload(job.document_id, stored))
    version = service.get_batch(batch.batch_id).version
    return service.start_batch(batch.batch_id, expected_version=version), jobs


def _entries(root: StorageRoot, kind: str) -> list[str]:
    return sorted(path.name for path in (root.path / kind).iterdir())


def _drain(worker: WorkerService) -> None:
    while worker.run_next():
        pass


def test_a_full_batch_and_a_second_batch_behind_it_share_one_worker_process(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor()
    worker = _worker(service, input_store, output_store, processor, clock, root)
    first_contents = [stubs.LIGHT + f"{index}\n".encode() for index in range(49)]
    first, _ = _running_batch(service, input_store, clock, [*first_contents, stubs.MALFORMED])
    clock.advance()
    second, _ = _running_batch(
        service, input_store, clock, [stubs.LIGHT + f"second {i}\n".encode() for i in range(10)]
    )
    _drain(worker)
    assert processor.started == 1
    first_states = [job.state for job in service.list_documents(first.batch_id)]
    assert first_states.count(DocumentState.COMPLETED) == 49
    assert first_states[-1] is DocumentState.FAILED
    assert {job.state for job in service.list_documents(second.batch_id)} == {
        DocumentState.COMPLETED
    }
    for batch in (first, second):
        assert service.get_batch(batch.batch_id).state is BatchState.FINISHED
    assert len(_entries(root, "outputs")) == 59
    assert _entries(root, "inputs") == []
    assert _entries(root, "work") == []


def test_a_detector_that_never_returns_ends_in_job_timeout_and_the_worker_is_replaced(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor(stubs.hanging_detector_pipeline, timeout_seconds=4)
    worker = _worker(service, input_store, output_store, processor, clock, root)
    _, (hung, following) = _running_batch(service, input_store, clock, [cv_pdf(), cv_pdf() + b"\n"])
    started = time.monotonic()
    done = worker.run(hung.document_id)
    assert time.monotonic() - started < 15
    assert done is not None
    assert done.state is DocumentState.FAILED
    assert done.error_code is ErrorCode.JOB_TIMEOUT
    assert not processor.alive
    assert _entries(root, "outputs") == []
    assert _entries(root, "work") == []
    again = worker.run(following.document_id)
    assert again is not None
    assert again.error_code is ErrorCode.JOB_TIMEOUT
    assert processor.started == 2


def test_a_timeout_does_not_disturb_the_next_document(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor(timeout_seconds=3)
    worker = _worker(service, input_store, output_store, processor, clock, root)
    batch, (hung, light) = _running_batch(service, input_store, clock, [stubs.HANG, stubs.LIGHT])
    _drain(worker)
    assert service.get_document(hung.document_id).error_code is ErrorCode.JOB_TIMEOUT
    assert service.get_document(light.document_id).state is DocumentState.COMPLETED
    assert processor.started == 2
    assert service.get_batch(batch.batch_id).state is BatchState.FINISHED
    assert len(_entries(root, "outputs")) == 1


def test_a_crashed_worker_fails_only_its_document_and_is_replaced(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor()
    worker = _worker(service, input_store, output_store, processor, clock, root)
    _, (crashed, light) = _running_batch(service, input_store, clock, [stubs.CRASH, stubs.LIGHT])
    _drain(worker)
    failed = service.get_document(crashed.document_id)
    assert failed.state is DocumentState.FAILED
    assert failed.error_code is ErrorCode.INTERNAL_ERROR
    assert service.get_document(light.document_id).state is DocumentState.COMPLETED
    assert processor.started == 2


def test_a_worker_that_cannot_start_claims_nothing(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor(stubs.failing_factory)
    worker = _worker(service, input_store, output_store, processor, clock, root)
    _, (job,) = _running_batch(service, input_store, clock, [stubs.LIGHT])
    with pytest.raises(ProcessingCrashedError):
        worker.run(job.document_id)
    assert service.get_document(job.document_id).state is DocumentState.UPLOADED
    assert not processor.alive


def test_graceful_shutdown_interrupts_a_document_that_does_not_finish(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor()
    worker = _worker(service, input_store, output_store, processor, clock, root)
    _, (hung, waiting) = _running_batch(service, input_store, clock, [stubs.HANG, stubs.LIGHT])
    loop = WorkerLoop(worker, processor, idle_seconds=0.05, shutdown_grace_seconds=0.5)
    loop.start()
    deadline = time.monotonic() + 20
    while service.get_document(hung.document_id).state is not DocumentState.PROCESSING:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    loop.stop()
    assert not loop.running
    assert not processor.alive
    stopped = service.get_document(hung.document_id)
    assert stopped.state is DocumentState.FAILED
    assert stopped.error_code is ErrorCode.JOB_INTERRUPTED
    assert service.get_document(waiting.document_id).state is DocumentState.UPLOADED
    assert _entries(root, "outputs") == []


def test_a_restart_fails_the_interrupted_document_and_finishes_the_rest(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    batch, (held, waiting) = _running_batch(
        service, input_store, clock, [stubs.LIGHT, stubs.LIGHT + b"2"]
    )
    service.apply(held.document_id, lambda j, at: j.start_validation(at))
    processor = make_processor()
    worker = _worker(service, input_store, output_store, processor, clock, root)
    loop = WorkerLoop(worker, processor, idle_seconds=0.05)
    loop.start()
    try:
        deadline = time.monotonic() + 30
        while service.get_batch(batch.batch_id).state is not BatchState.FINISHED:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        loop.stop()
    assert service.get_document(held.document_id).error_code is ErrorCode.JOB_INTERRUPTED
    assert service.get_document(waiting.document_id).state is DocumentState.COMPLETED


def test_the_api_stays_responsive_while_the_worker_is_busy(
    service: JobService,
    uploads: UploadService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor()
    worker = _worker(service, input_store, output_store, processor, clock, root)
    loop = WorkerLoop(worker, processor, idle_seconds=0.05)
    runtime = Runtime(service, uploads, Settings(), loop)
    batch = service.create_batch()
    for index in range(3):
        clock.advance()
        uploaded_document(service, input_store, batch.batch_id, content=stubs.BUSY + bytes([index]))
    with TestClient(create_app(runtime)) as client:
        version = client.get(f"/api/batches/{batch.batch_id}").json()["version"]
        started = client.post(
            f"/api/batches/{batch.batch_id}/start", json={"expected_version": version}
        )
        assert started.status_code == 200
        deadline = time.monotonic() + 30
        latencies: list[float] = []
        busy_seen = False
        while service.get_batch(batch.batch_id).state is not BatchState.FINISHED:
            assert time.monotonic() < deadline
            states = {job.state for job in service.list_documents(batch.batch_id)}
            busy_seen = busy_seen or DocumentState.PROCESSING in states
            before = time.monotonic()
            assert client.get("/api/health").status_code == 200
            latencies.append(time.monotonic() - before)
            time.sleep(0.02)
    assert busy_seen
    assert len(latencies) > 10
    assert max(latencies) < 0.5
    assert not loop.running
    assert not processor.alive


# ------------------------------------------------------------------ real pipeline, synthetic files


@pytest.mark.parametrize(
    ("fmt", "build", "hidden"),
    [
        (DocumentFormat.PDF, cv_pdf, frozenset()),
        (
            DocumentFormat.PDF,
            lambda: with_hidden(cv_pdf(), "embedded_files", "javascript", "invisible_text"),
            frozenset(
                {
                    HiddenContentCategory.EMBEDDED_FILES,
                    HiddenContentCategory.JAVASCRIPT,
                    HiddenContentCategory.INVISIBLE_TEXT,
                }
            ),
        ),
        (DocumentFormat.DOCX, docx_fixture.cv_docx, frozenset()),
        (
            DocumentFormat.DOCX,
            lambda: docx_fixture.with_hidden("comments", "hidden_text"),
            frozenset({HiddenContentCategory.COMMENTS, HiddenContentCategory.HIDDEN_TEXT}),
        ),
    ],
    ids=["pdf", "pdf-hidden", "docx", "docx-hidden"],
)
def test_the_production_pipeline_redacts_and_verifies_in_the_worker(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
    root: StorageRoot,
    make_processor: Callable[..., SubprocessProcessor],
    fmt: DocumentFormat,
    build: Callable[[], bytes],
    hidden: frozenset[HiddenContentCategory],
) -> None:
    processor = make_processor(build_pipeline, timeout_seconds=120)
    worker = _worker(service, input_store, output_store, processor, clock, root)
    _, (job,) = _running_batch(service, input_store, clock, [build()], fmt)
    done = worker.run(job.document_id)
    assert done is not None
    assert done.state in {DocumentState.COMPLETED, DocumentState.REVIEW_REQUIRED}, done.error_code
    assert done.verification is not None
    assert done.verification.outcome is VerificationOutcome.PASSED
    assert set(done.hidden_removed.as_dict()) == hidden
    assert done.finding_counts is not None
    assert len(_entries(root, "outputs")) == 1
    assert _entries(root, "work") == []
    if done.state is DocumentState.COMPLETED:
        assert _entries(root, "inputs") == []


def test_the_worker_process_is_gone_after_close(
    make_processor: Callable[..., SubprocessProcessor],
) -> None:
    processor = make_processor()
    with processor.session():
        assert processor.alive
    processor.close()
    assert not processor.alive
