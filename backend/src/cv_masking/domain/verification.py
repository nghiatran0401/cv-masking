from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from cv_masking.domain._validation import (
    require_identifier,
    require_int,
    require_semver,
    require_utc,
)
from cv_masking.domain.codes import ERROR_CODE_GROUPS, CodeGroup, ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.ids import ObjectRef
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES
from cv_masking.domain.policy import EntityType

VERIFY_FAILURE_PRECEDENCE: Final = (
    ErrorCode.VERIFY_RESIDUAL_FINDING,
    ErrorCode.VERIFY_RESIDUAL_DETECTION,
    ErrorCode.VERIFY_RESIDUAL_METADATA,
    ErrorCode.VERIFY_OUTPUT_INVALID,
    ErrorCode.VERIFY_PAGE_COUNT_MISMATCH,
    ErrorCode.VERIFY_STRUCTURE_MISMATCH,
)
"""Most serious first: leaked data outranks a broken or mismatched output."""


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ResidualCounts:
    """Leftover entity types and pages after verification. Never values."""

    items: tuple[tuple[EntityType, int, tuple[int, ...]], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise InvariantError("ResidualCounts.items must be a tuple")
        seen: set[EntityType] = set()
        for item in self.items:
            if not (isinstance(item, tuple) and len(item) == 3):
                raise InvariantError("ResidualCounts.items must be (type, count, pages)")
            entity_type, count, pages = item
            if not isinstance(entity_type, EntityType):
                raise InvariantError("ResidualCounts keys must be EntityType values")
            if entity_type in seen:
                raise InvariantError("ResidualCounts keys must be unique")
            seen.add(entity_type)
            require_int(count, "ResidualCounts count", minimum=1)
            if not isinstance(pages, tuple) or pages != tuple(sorted(set(pages))):
                raise InvariantError("ResidualCounts pages must be sorted unique integers")
            for page in pages:
                require_int(page, "ResidualCounts page", minimum=1, maximum=HARD_MAX_PDF_PAGES)
        order = list(EntityType)
        if [entity for entity, _, _ in self.items] != sorted(seen, key=order.index):
            raise InvariantError("ResidualCounts items must be in EntityType order")

    @classmethod
    def from_hits(cls, hits: Mapping[EntityType, tuple[int, Iterable[int]]]) -> "ResidualCounts":
        items: list[tuple[EntityType, int, tuple[int, ...]]] = []
        for entity in EntityType:
            if entity not in hits:
                continue
            count, pages = hits[entity]
            items.append((entity, count, tuple(sorted(set(pages)))))
        return cls(tuple(items))


NO_RESIDUAL: Final = ResidualCounts()


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of independently re-checking one output file."""

    outcome: VerificationOutcome
    failure_codes: frozenset[ErrorCode]
    output_ref: ObjectRef
    verifier_id: str
    verifier_version: str
    verified_at: datetime
    residual: ResidualCounts = NO_RESIDUAL

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
        if not isinstance(self.residual, ResidualCounts):
            raise InvariantError("VerificationResult.residual must be ResidualCounts")
        if self.residual.items and self.outcome is not VerificationOutcome.FAILED:
            raise InvariantError("only a FAILED verification may carry residual counts")
        require_identifier(self.verifier_id, "VerificationResult.verifier_id")
        require_semver(self.verifier_version, "VerificationResult.verifier_version")
        require_utc(self.verified_at, "VerificationResult.verified_at")

    @property
    def passed(self) -> bool:
        return self.outcome is VerificationOutcome.PASSED

    @property
    def primary_failure_code(self) -> ErrorCode | None:
        """The failure code shown to HR, chosen by VERIFY_FAILURE_PRECEDENCE."""
        return next((c for c in VERIFY_FAILURE_PRECEDENCE if c in self.failure_codes), None)
