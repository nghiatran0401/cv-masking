"""The local job queue: one worker, one document at a time (D-33).

The queue is the persisted state itself: the next job is the oldest UPLOADED
document of the oldest RUNNING batch, so nothing is lost on restart and there
is no in-memory backlog to bound. A document is claimed with an optimistic
state change (UPLOADED → VALIDATING), so delivering it twice processes it once.

All CPU-heavy work runs in the isolated processor. This module writes every
metadata change and stores the output, which the processor only returns as
bytes. Any error fails the one document it concerns, never the batch.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Final

from cv_masking.application.jobs import JobService, Transition
from cv_masking.domain.batch import BatchState
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import INTERRUPTIBLE_STATES, DocumentJob, DocumentState
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import DocumentId
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.clock import Clock
from cv_masking.ports.metadata import RecordNotFoundError
from cv_masking.ports.processing import (
    DocumentProcessor,
    ProcessingCrashedError,
    ProcessingError,
    ProcessingSession,
    ProcessingStoppedError,
    ProcessingTimeoutError,
)
from cv_masking.ports.storage import (
    InputStore,
    ObjectSink,
    OutputStore,
    StorageError,
    StorageSweeper,
    StoredObject,
)

logger = logging.getLogger("cv_masking.worker")

MAINTENANCE_INTERVAL_SECONDS: Final = 600.0
"""The sweeper and reconciliation run at startup and then every 10 minutes."""
IDLE_POLL_SECONDS: Final = 1.0
SHUTDOWN_GRACE_SECONDS: Final = 10.0


class _AbandonedError(Exception):
    """Someone else changed or deleted the document (cancel, purge); stop quietly."""


class WorkerService:
    __slots__ = ("_clock", "_inputs", "_jobs", "_outputs", "_processor", "_sweeper")

    def __init__(
        self,
        jobs: JobService,
        inputs: InputStore,
        outputs: OutputStore,
        processor: DocumentProcessor,
        clock: Clock,
        sweeper: StorageSweeper | None = None,
    ) -> None:
        self._jobs = jobs
        self._inputs = inputs
        self._outputs = outputs
        self._processor = processor
        self._clock = clock
        self._sweeper = sweeper

    # ------------------------------------------------------------------ startup / hygiene

    def recover(self) -> int:
        """Fail every document a previous run left in the worker's hands (JOB_INTERRUPTED)."""
        recovered = 0
        for job in self._all_documents():
            if job.state not in INTERRUPTIBLE_STATES:
                continue
            try:
                self._jobs.apply(job.document_id, lambda current, at: current.interrupt(at))
            except (InvalidTransitionError, RecordNotFoundError):
                continue
            recovered += 1
        logger.info("worker recovered interrupted=%d", recovered)
        return recovered

    def maintain(self) -> None:
        """Remove crash leftovers and files no document needs (D-23, D-26)."""
        if self._sweeper is not None:
            try:
                report = self._sweeper.sweep(self._clock.now())
            except StorageError as error:
                logger.warning("storage sweep failed code=%s", error.code)
            else:
                logger.info("storage swept removed=%d failed=%d", report.removed, report.failed)
        try:
            self._jobs.reconcile_storage()
        except StorageError as error:
            logger.warning("storage reconcile failed code=%s", error.code)

    # ------------------------------------------------------------------ queue

    def next_document(self) -> DocumentId | None:
        for batch in self._jobs.list_batches():
            if batch.state is not BatchState.RUNNING:
                continue
            for job in self._jobs.list_documents(batch.batch_id):
                if job.state is DocumentState.UPLOADED:
                    return job.document_id
        return None

    def run_next(self) -> bool:
        """Process the next waiting document; False if there is none."""
        document_id = self.next_document()
        if document_id is None:
            return False
        self.run(document_id)
        return True

    def run(self, document_id: DocumentId) -> DocumentJob | None:
        """Take one document from UPLOADED to a settled state.

        Returns None if the document was not waiting (already taken, cancelled,
        purged, or its batch is not running) or was purged while it ran. Raises
        ProcessingCrashedError only if no worker could be started, before the
        document is claimed.
        """
        with self._processor.session() as session:
            job = self._claim(document_id)
            if job is None:
                return None
            try:
                return self._drive(session, job)
            except _AbandonedError:
                logger.info("document %s left the queue during processing", document_id)
                return None
            except Exception as error:  # noqa: BLE001 - any bug fails this document closed
                logger.error("document %s worker error type=%s", document_id, type(error).__name__)
                return self._fail_if_held(document_id, ErrorCode.INTERNAL_ERROR)

    # ------------------------------------------------------------------ one document

    def _claim(self, document_id: DocumentId) -> DocumentJob | None:
        try:
            job = self._jobs.get_document(document_id)
            if self._jobs.get_batch(job.batch_id).state is not BatchState.RUNNING:
                return None
            return self._jobs.apply(document_id, lambda current, at: current.start_validation(at))
        except (InvalidTransitionError, RecordNotFoundError):
            return None

    def _drive(self, session: ProcessingSession, job: DocumentJob) -> DocumentJob | None:
        document_id = job.document_id
        try:
            return self._pipeline(session, job)
        except ProcessingTimeoutError:
            logger.info("document %s timed out", document_id)
            return self._fail_if_held(document_id, ErrorCode.JOB_TIMEOUT)
        except ProcessingStoppedError:
            logger.info("document %s interrupted by shutdown", document_id)
            return self._interrupt_if_held(document_id)
        except ProcessingCrashedError:
            logger.info("document %s worker crashed", document_id)
            return self._fail_if_held(document_id, ErrorCode.INTERNAL_ERROR)

    def _pipeline(self, session: ProcessingSession, job: DocumentJob) -> DocumentJob:
        document_id = job.document_id
        source = _source_of(job)
        checked = session.validate(source)
        if checked.failure is not None:
            code = checked.failure
            return self._change(document_id, lambda current, at: current.fail(code, at))
        if checked.review:
            reasons = checked.review
            return self._change(
                document_id, lambda current, at: current.validation_needs_review(reasons, at)
            )
        hidden = checked.hidden_removed
        self._change(document_id, lambda current, at: current.validation_passed(at, hidden))
        policy = self._jobs.get_batch(job.batch_id).policy
        self._change(document_id, lambda current, at: current.start_processing(policy, at))
        processed = session.process(policy)
        if processed.failure is not None or processed.output is None:
            code = processed.failure or ErrorCode.INTERNAL_ERROR
            return self._change(document_id, lambda current, at: current.fail(code, at))
        counts = processed.finding_counts
        if counts is None:
            return self._change(
                document_id, lambda current, at: current.fail(ErrorCode.INTERNAL_ERROR, at)
            )
        try:
            stored = self._store(source.document_format, processed.output)
        except StorageError:
            return self._change(
                document_id,
                lambda current, at: current.fail(ErrorCode.REDACT_OUTPUT_WRITE_FAILED, at),
            )
        reasons = processed.review
        try:
            self._inputs.verify(source)
            self._change(
                document_id,
                lambda current, at: current.output_written(stored.ref, counts, reasons, at),
            )
        except StorageError as error:
            self._discard(stored)
            code = error.code
            return self._change(document_id, lambda current, at: current.fail(code, at))
        except BaseException:
            self._discard(stored)
            raise
        verified = session.verify(stored)
        if verified.failure is not None or verified.result is None:
            code = verified.failure or ErrorCode.INTERNAL_ERROR
            return self._change(document_id, lambda current, at: current.fail(code, at))
        result = verified.result
        finished = self._change(
            document_id, lambda current, at: current.record_verification(result, at)
        )
        logger.info("document %s processed state=%s", document_id, finished.state)
        return finished

    def _store(self, fmt: DocumentFormat, output: bytes) -> StoredObject:
        def produce(sink: ObjectSink) -> None:
            sink.write(output)

        return self._outputs.save(fmt, produce, max_bytes=HARD_MAX_FILE_BYTES)

    def _discard(self, stored: StoredObject) -> None:
        try:
            self._outputs.delete(stored.ref, stored.document_format)
        except StorageError as error:
            logger.warning("output deletion deferred to reconcile code=%s", error.code)

    def _change(self, document_id: DocumentId, transition: Transition) -> DocumentJob:
        """Apply a transition to a document this worker holds.

        While the worker holds a document (VALIDATING, PROCESSING, VERIFYING)
        nobody else may change it, so a refused transition there is a bug and
        fails the document. Anywhere else (QUEUED, or deleted) it means HR
        cancelled or purged it.
        """
        try:
            return self._jobs.apply(document_id, transition)
        except RecordNotFoundError:
            raise _AbandonedError from None
        except InvalidTransitionError:
            if self._fail_if_held(document_id, ErrorCode.INTERNAL_ERROR) is None:
                raise _AbandonedError from None
            raise

    def _fail_if_held(self, document_id: DocumentId, code: ErrorCode) -> DocumentJob | None:
        return self._settle_if_held(document_id, lambda current, at: current.fail(code, at))

    def _interrupt_if_held(self, document_id: DocumentId) -> DocumentJob | None:
        return self._settle_if_held(document_id, lambda current, at: current.interrupt(at))

    def _settle_if_held(
        self, document_id: DocumentId, transition: Transition
    ) -> DocumentJob | None:
        try:
            current = self._jobs.get_document(document_id)
            if current.state not in INTERRUPTIBLE_STATES:
                return None
            return self._jobs.apply(document_id, transition)
        except (InvalidTransitionError, RecordNotFoundError):
            return None

    def _all_documents(self) -> list[DocumentJob]:
        return [
            job
            for batch in self._jobs.list_batches()
            for job in self._jobs.list_documents(batch.batch_id)
        ]


def _source_of(job: DocumentJob) -> StoredObject:
    if (
        job.input_ref is None
        or job.document_format is None
        or job.content_sha256 is None
        or job.size_bytes is None
    ):
        raise InvalidTransitionError("process", job.state, "document has no stored input")
    return StoredObject(job.input_ref, job.document_format, job.content_sha256, job.size_bytes)


class WorkerLoop:
    """The single background thread that feeds the worker and runs maintenance.

    The API's event loop never runs document work: it only calls ``notify``.
    """

    __slots__ = (
        "_grace",
        "_idle",
        "_interval",
        "_monotonic",
        "_processor",
        "_stopping",
        "_thread",
        "_wake",
        "_worker",
    )

    def __init__(
        self,
        worker: WorkerService,
        processor: DocumentProcessor,
        *,
        idle_seconds: float = IDLE_POLL_SECONDS,
        maintenance_interval_seconds: float = MAINTENANCE_INTERVAL_SECONDS,
        shutdown_grace_seconds: float = SHUTDOWN_GRACE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._worker = worker
        self._processor = processor
        self._idle = idle_seconds
        self._interval = maintenance_interval_seconds
        self._grace = shutdown_grace_seconds
        self._monotonic = monotonic
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Recover and clean up before the first request, then start the thread."""
        if self._thread is not None:
            raise RuntimeError("the worker loop was already started")
        self._worker.recover()
        self._worker.maintain()
        self._thread = threading.Thread(target=self._run, name="cv-masking-worker", daemon=True)
        self._thread.start()

    def notify(self) -> None:
        """Documents may be waiting (a batch started); check now instead of at the next poll."""
        self._wake.set()

    def stop(self) -> None:
        """Let the current document finish within the grace period, else interrupt it."""
        self._stopping.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(self._grace)
        self._processor.close()
        if thread is not None:
            thread.join()

    def _run(self) -> None:
        next_maintenance = self._monotonic() + self._interval
        while not self._stopping.is_set():
            if self._monotonic() >= next_maintenance:
                self._worker.maintain()
                next_maintenance = self._monotonic() + self._interval
            self._wake.clear()
            try:
                busy = self._worker.run_next()
            except ProcessingError:
                logger.warning("worker could not start; will retry")
                busy = False
            except Exception as error:  # noqa: BLE001 - the loop must survive any error
                logger.error("worker loop error type=%s", type(error).__name__)
                busy = False
            if not busy:
                self._wake.wait(self._idle)
