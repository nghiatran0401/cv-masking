"""Helpers that drive synthetic documents through the job service."""

from datetime import datetime, timedelta

from domain_builders import COUNTS, T0, VERIFIER_ID, VERIFIER_VERSION

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore
from cv_masking.application import JobService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import BatchId
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.storage import ObjectSink

SYNTHETIC_INPUT = b"%PDF-synthetic input bytes for tests only\n"
SYNTHETIC_OUTPUT = b"%PDF-synthetic redacted output bytes for tests only\n"


class ManualClock:
    """A clock the test moves by hand."""

    def __init__(self, start: datetime = T0) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta = timedelta(minutes=1)) -> datetime:
        self.current += delta
        return self.current


def uploaded_document(
    service: JobService,
    input_store: LocalInputStore,
    batch_id: BatchId,
    fmt: DocumentFormat = DocumentFormat.PDF,
    content: bytes = SYNTHETIC_INPUT,
) -> DocumentJob:
    job = service.add_document(batch_id)
    stored = input_store.save_stream(fmt, [content], max_bytes=1_000_000)
    return service.record_upload(job.document_id, stored)


def queued_document(
    service: JobService, input_store: LocalInputStore, batch_id: BatchId
) -> DocumentJob:
    job = uploaded_document(service, input_store, batch_id)
    job = service.apply(job.document_id, lambda j, at: j.start_validation(at))
    return service.apply(job.document_id, lambda j, at: j.validation_passed(at))


def verifying_document(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    batch_id: BatchId,
    reasons: frozenset[ReviewReason] = frozenset(),
    output: bytes = SYNTHETIC_OUTPUT,
) -> DocumentJob:
    job = queued_document(service, input_store, batch_id)
    job = service.apply(job.document_id, lambda j, at: j.start_processing(MaskingPolicy(), at))
    fmt = job.document_format or DocumentFormat.PDF
    stored = output_store.save(fmt, lambda sink: _write(sink, output), max_bytes=1_000_000)
    return service.apply(
        job.document_id, lambda j, at: j.output_written(stored.ref, COUNTS, reasons, at)
    )


def _write(sink: ObjectSink, data: bytes) -> None:
    sink.write(data)


def verified(
    service: JobService,
    job: DocumentJob,
    outcome: VerificationOutcome = VerificationOutcome.PASSED,
    codes: frozenset[ErrorCode] = frozenset(),
) -> DocumentJob:
    def record(current: DocumentJob, at: datetime) -> DocumentJob:
        assert current.output_ref is not None
        result = VerificationResult(
            outcome=outcome,
            failure_codes=codes,
            output_ref=current.output_ref,
            verifier_id=VERIFIER_ID,
            verifier_version=VERIFIER_VERSION,
            verified_at=at,
        )
        return current.record_verification(result, at)

    return service.apply(job.document_id, record)
