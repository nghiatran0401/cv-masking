from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cv_masking.domain._validation import require_identifier, require_semver, require_utc
from cv_masking.domain.codes import ERROR_CODE_GROUPS, CodeGroup, ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.ids import ObjectRef


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of independently re-checking one output file."""

    outcome: VerificationOutcome
    failure_codes: frozenset[ErrorCode]
    output_ref: ObjectRef
    verifier_id: str
    verifier_version: str
    verified_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, VerificationOutcome):
            raise InvariantError("VerificationResult.outcome must be a VerificationOutcome")
        if not isinstance(self.failure_codes, frozenset) or not all(
            isinstance(code, ErrorCode) for code in self.failure_codes
        ):
            raise InvariantError("VerificationResult.failure_codes must be ErrorCode values")
        if any(
            ERROR_CODE_GROUPS[code] is not CodeGroup.VERIFICATION for code in self.failure_codes
        ):
            raise InvariantError("VerificationResult.failure_codes must be VERIFY_* codes")
        if self.outcome is VerificationOutcome.FAILED and not self.failure_codes:
            raise InvariantError("a FAILED verification needs at least one failure code")
        if self.outcome is not VerificationOutcome.FAILED and self.failure_codes:
            raise InvariantError("only a FAILED verification may carry failure codes")
        if not isinstance(self.output_ref, ObjectRef):
            raise InvariantError("VerificationResult.output_ref must be an ObjectRef")
        require_identifier(self.verifier_id, "VerificationResult.verifier_id")
        require_semver(self.verifier_version, "VerificationResult.verifier_version")
        require_utc(self.verified_at, "VerificationResult.verified_at")

    @property
    def passed(self) -> bool:
        return self.outcome is VerificationOutcome.PASSED
