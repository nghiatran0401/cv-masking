"""Builders for synthetic domain objects. No document content is involved anywhere."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import BatchId, DocumentId, FindingId, ObjectRef, Sha256Digest
from cv_masking.domain.limits import RETENTION_WINDOW
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
DIGEST = Sha256Digest("ab" * 32)
SIZE_BYTES = 4096
COUNTS = FindingCounts.from_mapping({EntityType.EMAIL: 1, EntityType.PHONE: 2})
VERIFIER_ID = "synthetic-verifier"
VERIFIER_VERSION = "1.0.0"

HIDDEN_CONTENT_REASON = {
    DocumentFormat.PDF: ReviewReason.PDF_HIDDEN_CONTENT,
    DocumentFormat.DOCX: ReviewReason.DOCX_HIDDEN_CONTENT,
}
BLOCKING_REASON = {
    DocumentFormat.PDF: ReviewReason.PDF_ENCRYPTED,
    DocumentFormat.DOCX: ReviewReason.DOCX_ENCRYPTED,
}


def new_batch_id() -> BatchId:
    return BatchId(uuid4())


def new_document_id() -> DocumentId:
    return DocumentId(uuid4())


def new_finding_id() -> FindingId:
    return FindingId(uuid4())


def new_object_ref() -> ObjectRef:
    return ObjectRef(uuid4())


def later(job: DocumentJob, minutes: int = 1) -> datetime:
    return job.updated_at + timedelta(minutes=minutes)


def after_retention(job: DocumentJob) -> datetime:
    assert job.uploaded_at is not None
    return max(later(job), job.uploaded_at + RETENTION_WINDOW)


def verification_for(
    job: DocumentJob,
    outcome: VerificationOutcome = VerificationOutcome.PASSED,
    codes: frozenset[ErrorCode] = frozenset(),
) -> VerificationResult:
    """A result for the job's output, or for an unrelated output if the job has none."""
    return VerificationResult(
        outcome=outcome,
        failure_codes=codes,
        output_ref=job.output_ref or new_object_ref(),
        verifier_id=VERIFIER_ID,
        verifier_version=VERIFIER_VERSION,
        verified_at=later(job),
    )


def created() -> DocumentJob:
    return DocumentJob.create(new_document_id(), new_batch_id(), T0)


def uploaded(fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    job = created()
    return job.mark_uploaded(
        document_format=fmt, content_sha256=DIGEST, size_bytes=SIZE_BYTES, at=later(job)
    )


def validating(fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    job = uploaded(fmt)
    return job.start_validation(later(job))


def queued(fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    job = validating(fmt)
    return job.validation_passed(later(job))


def processing(
    fmt: DocumentFormat = DocumentFormat.PDF, policy: MaskingPolicy | None = None
) -> DocumentJob:
    job = queued(fmt)
    return job.start_processing(policy or MaskingPolicy(), later(job))


def verifying(
    fmt: DocumentFormat = DocumentFormat.PDF,
    reasons: frozenset[ReviewReason] = frozenset(),
) -> DocumentJob:
    job = processing(fmt)
    return job.output_written(new_object_ref(), COUNTS, reasons, later(job))


def completed(fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    job = verifying(fmt)
    return job.record_verification(verification_for(job), later(job))


def validation_review(
    fmt: DocumentFormat = DocumentFormat.PDF,
    reasons: frozenset[ReviewReason] | None = None,
) -> DocumentJob:
    job = validating(fmt)
    chosen = reasons if reasons is not None else frozenset({HIDDEN_CONTENT_REASON[fmt]})
    return job.validation_needs_review(chosen, later(job))


def findings_review(fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    job = verifying(fmt, frozenset({ReviewReason.DETECT_LOW_CONFIDENCE}))
    return job.record_verification(verification_for(job), later(job))


def verifier_review(fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    job = verifying(fmt)
    return job.record_verification(
        verification_for(job, VerificationOutcome.REVIEW_REQUIRED), later(job)
    )


def failed() -> DocumentJob:
    job = validating()
    return job.fail(ErrorCode.PDF_MALFORMED, later(job))


def rejected() -> DocumentJob:
    job = validation_review()
    return job.deny_review(later(job))


def cancelled() -> DocumentJob:
    job = queued()
    return job.cancel(later(job))


def rebuild(job: DocumentJob, **changes: object) -> DocumentJob:
    """Construct a job from field values, as a repository does when loading a stored row."""
    fields = {name: getattr(job, name) for name in DocumentJob.__dataclass_fields__}
    fields.update(changes)
    return DocumentJob(**fields)


def job_in_state(state: DocumentState, fmt: DocumentFormat = DocumentFormat.PDF) -> DocumentJob:
    """A representative job; REVIEW_REQUIRED is an approvable hidden-content review."""
    match state:
        case DocumentState.CREATED:
            return created()
        case DocumentState.UPLOADED:
            return uploaded(fmt)
        case DocumentState.VALIDATING:
            return validating(fmt)
        case DocumentState.QUEUED:
            return queued(fmt)
        case DocumentState.PROCESSING:
            return processing(fmt)
        case DocumentState.VERIFYING:
            return verifying(fmt)
        case DocumentState.REVIEW_REQUIRED:
            return validation_review(fmt)
        case DocumentState.COMPLETED:
            return completed(fmt)
        case DocumentState.FAILED:
            return failed()
        case DocumentState.REJECTED:
            return rejected()
        case DocumentState.CANCELLED:
            return cancelled()
