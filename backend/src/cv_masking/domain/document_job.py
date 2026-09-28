"""Document job aggregate and its state machine (docs/error-codes.md §2).

A DocumentJob is immutable. Each command validates the current state and
returns a new job with ``version`` incremented; anything not explicitly allowed
raises InvalidTransitionError. ``__post_init__`` re-checks every structural
invariant, so a job rebuilt from storage with an impossible combination of
fields fails closed.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from cv_masking.domain._validation import require_bool, require_int, require_utc
from cv_masking.domain.codes import (
    ERROR_CODE_GROUPS,
    INSPECTABLE_FAILURE_CODES,
    POST_PROCESSING_REVIEW_KINDS,
    REVIEW_REASON_KINDS,
    VALIDATION_REVIEW_KINDS,
    CodeGroup,
    ErrorCode,
    ReviewKind,
    ReviewReason,
    error_format,
    reason_format,
)
from cv_masking.domain.errors import InvalidTransitionError, InvariantError
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import NO_HIDDEN_CONTENT, HiddenContentCounts
from cv_masking.domain.ids import BatchId, DocumentId, ObjectRef, Sha256Digest
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES, MAX_PROCESSING_ATTEMPTS
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult


class DocumentState(StrEnum):
    CREATED = "created"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    QUEUED = "queued"
    PROCESSING = "processing"
    VERIFYING = "verifying"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


TERMINAL_STATES: Final = frozenset(
    {
        DocumentState.COMPLETED,
        DocumentState.FAILED,
        DocumentState.REJECTED,
        DocumentState.CANCELLED,
    }
)
CANCELLABLE_STATES: Final = frozenset(
    {DocumentState.CREATED, DocumentState.UPLOADED, DocumentState.QUEUED}
)
"""Only documents still waiting for the worker (D-33)."""
INTERRUPTIBLE_STATES: Final = frozenset(
    {DocumentState.VALIDATING, DocumentState.PROCESSING, DocumentState.VERIFYING}
)
"""States the worker holds a document in; left there only by a crash or shutdown."""

_STATES_WITH_UPLOAD: Final = frozenset(
    {
        DocumentState.UPLOADED,
        DocumentState.VALIDATING,
        DocumentState.QUEUED,
        DocumentState.PROCESSING,
        DocumentState.VERIFYING,
        DocumentState.REVIEW_REQUIRED,
        DocumentState.COMPLETED,
        DocumentState.REJECTED,
    }
)
_STATES_WITHOUT_OUTPUT: Final = frozenset(
    {
        DocumentState.CREATED,
        DocumentState.UPLOADED,
        DocumentState.VALIDATING,
        DocumentState.QUEUED,
        DocumentState.PROCESSING,
    }
)
_STATES_WITH_POLICY: Final = frozenset(
    {DocumentState.PROCESSING, DocumentState.VERIFYING, DocumentState.COMPLETED}
)
_STATES_BEFORE_EXTRACTION: Final = frozenset(
    {DocumentState.CREATED, DocumentState.UPLOADED, DocumentState.VALIDATING}
)

_UPLOAD_REJECTION_GROUPS: Final = frozenset(
    {CodeGroup.UPLOAD, CodeGroup.STORAGE, CodeGroup.INTERNAL}
)
_FAILURE_GROUPS_BY_STATE: Final = {
    DocumentState.VALIDATING: frozenset(
        {CodeGroup.VALIDATION, CodeGroup.STORAGE, CodeGroup.INTERNAL}
    ),
    DocumentState.PROCESSING: frozenset(
        {CodeGroup.PROCESSING, CodeGroup.STORAGE, CodeGroup.INTERNAL}
    ),
    DocumentState.VERIFYING: frozenset({CodeGroup.STORAGE, CodeGroup.INTERNAL}),
}
_FAILURE_CODES_ANY_STAGE: Final = frozenset({ErrorCode.JOB_TIMEOUT})


@dataclass(frozen=True, slots=True)
class DocumentJob:
    document_id: DocumentId
    batch_id: BatchId
    state: DocumentState
    created_at: datetime
    updated_at: datetime
    version: int
    document_format: DocumentFormat | None = None
    input_ref: ObjectRef | None = None
    content_sha256: Sha256Digest | None = None
    size_bytes: int | None = None
    uploaded_at: datetime | None = None
    attempt: int = 0
    policy: MaskingPolicy | None = None
    hidden_removed: HiddenContentCounts = NO_HIDDEN_CONTENT
    findings_review_approved: bool = False
    output_ref: ObjectRef | None = None
    finding_counts: FindingCounts | None = None
    review_reasons: frozenset[ReviewReason] = frozenset()
    verification: VerificationResult | None = None
    error_code: ErrorCode | None = None

    def __post_init__(self) -> None:
        self._check_types()
        self._check_upload_fields()
        self._check_processing_fields()
        self._check_review_fields()
        self._check_outcome_fields()

    # ------------------------------------------------------------------ creation

    @classmethod
    def create(cls, document_id: DocumentId, batch_id: BatchId, at: datetime) -> "DocumentJob":
        return cls(
            document_id=document_id,
            batch_id=batch_id,
            state=DocumentState.CREATED,
            created_at=at,
            updated_at=at,
            version=0,
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def can_approve_review(self) -> bool:
        """HR may keep the output: only findings reasons, and verification PASSED (D-34)."""
        kinds = {REVIEW_REASON_KINDS[reason] for reason in self.review_reasons}
        return (
            self.state is DocumentState.REVIEW_REQUIRED
            and kinds == {ReviewKind.FINDINGS}
            and self._verification_passed()
        )

    @property
    def has_downloadable_output(self) -> bool:
        """HR may open COMPLETED, findings-held, and inspectable residual failures (D-46)."""
        if self.output_ref is None:
            return False
        if self.state in {DocumentState.COMPLETED, DocumentState.REVIEW_REQUIRED}:
            return True
        return self.state is DocumentState.FAILED and self.error_code in INSPECTABLE_FAILURE_CODES

    # ------------------------------------------------------------------ upload

    def mark_uploaded(
        self,
        *,
        document_format: DocumentFormat,
        input_ref: ObjectRef,
        content_sha256: Sha256Digest,
        size_bytes: int,
        at: datetime,
    ) -> "DocumentJob":
        self._require_state("mark_uploaded", DocumentState.CREATED)
        return self._advance(
            at,
            state=DocumentState.UPLOADED,
            document_format=document_format,
            input_ref=input_ref,
            content_sha256=content_sha256,
            size_bytes=size_bytes,
            uploaded_at=at,
        )

    def reject_upload(self, code: ErrorCode, at: datetime) -> "DocumentJob":
        self._require_state("reject_upload", DocumentState.CREATED)
        if (
            not isinstance(code, ErrorCode)
            or ERROR_CODE_GROUPS[code] not in _UPLOAD_REJECTION_GROUPS
        ):
            raise InvalidTransitionError("reject_upload", self.state, "code is not an upload error")
        return self._advance(at, state=DocumentState.FAILED, error_code=code)

    # ------------------------------------------------------------------ validation

    def start_validation(self, at: datetime) -> "DocumentJob":
        self._require_state("start_validation", DocumentState.UPLOADED)
        return self._advance(at, state=DocumentState.VALIDATING)

    def validation_passed(
        self, at: datetime, hidden_removed: HiddenContentCounts = NO_HIDDEN_CONTENT
    ) -> "DocumentJob":
        """``hidden_removed`` is what redaction will always remove (D-32)."""
        self._require_state("validation_passed", DocumentState.VALIDATING)
        return self._advance(at, state=DocumentState.QUEUED, hidden_removed=hidden_removed)

    def validation_needs_review(
        self, reasons: Iterable[ReviewReason], at: datetime
    ) -> "DocumentJob":
        self._require_state("validation_needs_review", DocumentState.VALIDATING)
        chosen = frozenset(reasons)
        if not chosen or not self._reasons_have_kinds(chosen, VALIDATION_REVIEW_KINDS):
            raise InvalidTransitionError(
                "validation_needs_review", self.state, "reasons must be validation reasons"
            )
        return self._advance(at, state=DocumentState.REVIEW_REQUIRED, review_reasons=chosen)

    # ------------------------------------------------------------------ review

    def approve_review(self, at: datetime) -> "DocumentJob":
        self._require_state("approve_review", DocumentState.REVIEW_REQUIRED)
        if self.can_approve_review:
            return self._advance(
                at,
                state=DocumentState.COMPLETED,
                review_reasons=frozenset(),
                findings_review_approved=True,
            )
        raise InvalidTransitionError(
            "approve_review", self.state, "these review reasons cannot be approved"
        )

    def deny_review(self, at: datetime) -> "DocumentJob":
        self._require_state("deny_review", DocumentState.REVIEW_REQUIRED)
        return self._advance(at, state=DocumentState.REJECTED, review_reasons=frozenset())

    # ------------------------------------------------------------------ processing

    def start_processing(self, policy: MaskingPolicy, at: datetime) -> "DocumentJob":
        self._require_state("start_processing", DocumentState.QUEUED)
        if self.attempt >= MAX_PROCESSING_ATTEMPTS:
            raise InvalidTransitionError("start_processing", self.state, "attempt limit reached")
        return self._advance(
            at, state=DocumentState.PROCESSING, policy=policy, attempt=self.attempt + 1
        )

    def output_written(
        self,
        output_ref: ObjectRef,
        finding_counts: FindingCounts,
        review_reasons: Iterable[ReviewReason],
        at: datetime,
    ) -> "DocumentJob":
        self._require_state("output_written", DocumentState.PROCESSING)
        chosen = frozenset(review_reasons)
        if not self._reasons_have_kinds(chosen, frozenset({ReviewKind.FINDINGS})):
            raise InvalidTransitionError(
                "output_written", self.state, "reasons must be findings reasons"
            )
        return self._advance(
            at,
            state=DocumentState.VERIFYING,
            output_ref=output_ref,
            finding_counts=finding_counts,
            review_reasons=chosen,
        )

    def record_verification(self, result: VerificationResult, at: datetime) -> "DocumentJob":
        self._require_state("record_verification", DocumentState.VERIFYING)
        if not isinstance(result, VerificationResult) or result.output_ref != self.output_ref:
            raise InvalidTransitionError(
                "record_verification", self.state, "result is not for this job's output"
            )
        if result.outcome is VerificationOutcome.FAILED:
            if not all(self._code_fits_format(code) for code in result.failure_codes):
                raise InvalidTransitionError(
                    "record_verification", self.state, "failure code does not fit the format"
                )
            return self._advance(
                at,
                state=DocumentState.FAILED,
                verification=result,
                review_reasons=frozenset(),
                error_code=result.primary_failure_code,
            )
        if result.outcome is VerificationOutcome.REVIEW_REQUIRED:
            return self._advance(
                at,
                state=DocumentState.REVIEW_REQUIRED,
                verification=result,
                review_reasons=self.review_reasons | {ReviewReason.VERIFY_REVIEW},
            )
        if self.review_reasons:
            return self._advance(at, state=DocumentState.REVIEW_REQUIRED, verification=result)
        return self._advance(at, state=DocumentState.COMPLETED, verification=result)

    def interrupt(self, at: datetime) -> "DocumentJob":
        """The worker stopped holding this document (crash, restart, shutdown): FAILED (D-33)."""
        self._require_state("interrupt", *INTERRUPTIBLE_STATES)
        return self._advance(
            at,
            state=DocumentState.FAILED,
            review_reasons=frozenset(),
            error_code=ErrorCode.JOB_INTERRUPTED,
        )

    # ------------------------------------------------------------------ failure / cancel

    def fail(self, code: ErrorCode, at: datetime) -> "DocumentJob":
        allowed_groups = _FAILURE_GROUPS_BY_STATE.get(self.state)
        if allowed_groups is None:
            raise InvalidTransitionError("fail", self.state)
        if not isinstance(code, ErrorCode) or not (
            ERROR_CODE_GROUPS[code] in allowed_groups or code in _FAILURE_CODES_ANY_STAGE
        ):
            raise InvalidTransitionError("fail", self.state, "code does not fit this stage")
        if not self._code_fits_format(code):
            raise InvalidTransitionError(
                "fail", self.state, "code does not fit the document format"
            )
        return self._advance(
            at, state=DocumentState.FAILED, review_reasons=frozenset(), error_code=code
        )

    def cancel(self, at: datetime) -> "DocumentJob":
        if self.state not in CANCELLABLE_STATES:
            raise InvalidTransitionError("cancel", self.state)
        return self._advance(
            at,
            state=DocumentState.CANCELLED,
            review_reasons=frozenset(),
            error_code=ErrorCode.JOB_CANCELLED,
        )

    # ------------------------------------------------------------------ helpers

    def _require_state(self, command: str, *allowed: DocumentState) -> None:
        if self.state not in allowed:
            raise InvalidTransitionError(command, self.state)

    def _advance(self, at: datetime, **changes: object) -> "DocumentJob":
        require_utc(at, "at")
        if at < self.updated_at:
            raise InvariantError("transition time must not be earlier than updated_at")
        return replace(self, updated_at=at, version=self.version + 1, **changes)  # type: ignore[arg-type]

    def _verification_passed(self) -> bool:
        return self.verification is not None and self.verification.passed

    def _reasons_have_kinds(
        self, reasons: frozenset[ReviewReason], kinds: frozenset[ReviewKind]
    ) -> bool:
        return all(
            isinstance(reason, ReviewReason)
            and REVIEW_REASON_KINDS[reason] in kinds
            and reason_format(reason) in (None, self.document_format)
            for reason in reasons
        )

    def _code_fits_format(self, code: ErrorCode) -> bool:
        return error_format(code) in (None, self.document_format)

    # ------------------------------------------------------------------ invariants

    def _check_types(self) -> None:
        checks: tuple[tuple[object, type | tuple[type, ...], str], ...] = (
            (self.document_id, DocumentId, "document_id"),
            (self.batch_id, BatchId, "batch_id"),
            (self.state, DocumentState, "state"),
            (self.document_format, (DocumentFormat, type(None)), "document_format"),
            (self.input_ref, (ObjectRef, type(None)), "input_ref"),
            (self.content_sha256, (Sha256Digest, type(None)), "content_sha256"),
            (self.policy, (MaskingPolicy, type(None)), "policy"),
            (self.output_ref, (ObjectRef, type(None)), "output_ref"),
            (self.finding_counts, (FindingCounts, type(None)), "finding_counts"),
            (self.verification, (VerificationResult, type(None)), "verification"),
            (self.hidden_removed, HiddenContentCounts, "hidden_removed"),
            (self.error_code, (ErrorCode, type(None)), "error_code"),
        )
        for value, expected, name in checks:
            if not isinstance(value, expected):
                raise InvariantError(f"DocumentJob.{name} has the wrong type")
        require_utc(self.created_at, "DocumentJob.created_at")
        require_utc(self.updated_at, "DocumentJob.updated_at")
        if self.updated_at < self.created_at:
            raise InvariantError("DocumentJob.updated_at must not precede created_at")
        require_int(self.version, "DocumentJob.version", minimum=0)
        require_int(self.attempt, "DocumentJob.attempt", minimum=0, maximum=MAX_PROCESSING_ATTEMPTS)
        require_bool(self.findings_review_approved, "DocumentJob.findings_review_approved")
        if not isinstance(self.review_reasons, frozenset) or not all(
            isinstance(reason, ReviewReason) for reason in self.review_reasons
        ):
            raise InvariantError("DocumentJob.review_reasons must be ReviewReason values")

    def _check_upload_fields(self) -> None:
        upload_fields = (
            self.document_format,
            self.input_ref,
            self.content_sha256,
            self.size_bytes,
            self.uploaded_at,
        )
        has_upload = all(field is not None for field in upload_fields)
        if not has_upload and any(field is not None for field in upload_fields):
            raise InvariantError("DocumentJob upload fields must be set together")
        if self.state in _STATES_WITH_UPLOAD and not has_upload:
            raise InvariantError("DocumentJob in this state must have upload fields")
        if self.state is DocumentState.CREATED and has_upload:
            raise InvariantError("a CREATED DocumentJob cannot have upload fields")
        if has_upload:
            require_int(
                self.size_bytes, "DocumentJob.size_bytes", minimum=1, maximum=HARD_MAX_FILE_BYTES
            )
            require_utc(self.uploaded_at, "DocumentJob.uploaded_at")
            uploaded_at = self.uploaded_at
            if isinstance(uploaded_at, datetime) and not (
                self.created_at <= uploaded_at <= self.updated_at
            ):
                raise InvariantError("DocumentJob.uploaded_at is outside the job lifetime")

    def _check_processing_fields(self) -> None:
        if self.state in _STATES_WITH_POLICY and (self.policy is None or self.attempt < 1):
            raise InvariantError("DocumentJob in this state must have a policy and attempt")
        if self.state in _STATES_WITHOUT_OUTPUT and (
            self.output_ref is not None
            or self.finding_counts is not None
            or self.verification is not None
        ):
            raise InvariantError("DocumentJob in this state cannot have output data")
        if self.state is DocumentState.VERIFYING and (
            self.output_ref is None or self.finding_counts is None or self.verification is not None
        ):
            raise InvariantError("a VERIFYING DocumentJob needs an output and no verification")
        if self.output_ref is not None and self.output_ref == self.input_ref:
            raise InvariantError("DocumentJob.output_ref must differ from input_ref")
        if self.verification is not None and self.verification.output_ref != self.output_ref:
            raise InvariantError("DocumentJob.verification does not match output_ref")
        if self.hidden_removed.items and self.state in _STATES_BEFORE_EXTRACTION:
            raise InvariantError("hidden content is only known after validation")

    def _check_review_fields(self) -> None:
        kinds = {REVIEW_REASON_KINDS[reason] for reason in self.review_reasons}
        if self.state is DocumentState.REVIEW_REQUIRED:
            if not kinds:
                raise InvariantError("a REVIEW_REQUIRED DocumentJob needs review reasons")
            if kinds <= VALIDATION_REVIEW_KINDS:
                if (
                    self.output_ref is not None
                    or self.verification is not None
                    or self.hidden_removed.items
                ):
                    raise InvariantError("validation review cannot have output data")
            elif kinds <= POST_PROCESSING_REVIEW_KINDS:
                if (
                    self.verification is None
                    or self.verification.outcome is VerificationOutcome.FAILED
                    or self.finding_counts is None
                ):
                    raise InvariantError("post-processing review needs a non-failed verification")
                if (ReviewKind.VERIFIER in kinds) != (
                    self.verification.outcome is VerificationOutcome.REVIEW_REQUIRED
                ):
                    raise InvariantError("VERIFY_REVIEW must match the verification outcome")
            else:
                raise InvariantError("validation and post-processing reasons cannot mix")
        elif self.state is DocumentState.VERIFYING:
            if not kinds <= {ReviewKind.FINDINGS}:
                raise InvariantError("a VERIFYING DocumentJob may only hold findings reasons")
        elif kinds:
            raise InvariantError("DocumentJob in this state cannot hold review reasons")
        if self.findings_review_approved and self.state is not DocumentState.COMPLETED:
            raise InvariantError("findings review approval only applies to COMPLETED jobs")

    def _check_outcome_fields(self) -> None:
        if self.state is DocumentState.COMPLETED and (
            self.verification is None
            or not self.verification.passed
            or self.output_ref is None
            or self.finding_counts is None
        ):
            raise InvariantError("a COMPLETED DocumentJob needs a PASSED verification")
        if self.state is DocumentState.FAILED:
            if (
                self.error_code is None
                or self.error_code is ErrorCode.JOB_CANCELLED
                or ERROR_CODE_GROUPS[self.error_code] is CodeGroup.SECURITY
                or not self._code_fits_format(self.error_code)
            ):
                raise InvariantError("a FAILED DocumentJob needs a document failure code")
        elif self.state is DocumentState.CANCELLED:
            if self.error_code is not ErrorCode.JOB_CANCELLED:
                raise InvariantError("a CANCELLED DocumentJob must carry JOB_CANCELLED")
        elif self.error_code is not None:
            raise InvariantError("only FAILED or CANCELLED jobs carry an error code")
