"""Masking policy (docs/masking-policy.md, policy version 2).

Mandatory entity types cannot be disabled: the only HR-selectable setting is
the salary toggle. Thresholds and labels are fixed per policy version.
Jobs stored under version 1 still load; new jobs record version 2.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from cv_masking.domain._validation import require_bool, require_finite_float
from cv_masking.domain.errors import InvariantError, PolicyError

POLICY_VERSION: Final = "2"
KNOWN_POLICY_VERSIONS: Final = frozenset({"1", "2"})
REDACT_THRESHOLD: Final = 0.85
DISCARD_THRESHOLD: Final = 0.50


class EntityType(StrEnum):
    CANDIDATE_NAME = "candidate_name"
    REFERENCE_NAME = "reference_name"
    EMAIL = "email"
    PHONE = "phone"
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    POSTAL_ADDRESS = "postal_address"
    DATE_OF_BIRTH = "date_of_birth"
    GENDER = "gender"
    MARITAL_STATUS = "marital_status"
    NATIONALITY = "nationality"
    RELIGION = "religion"
    ETHNICITY = "ethnicity"
    HEALTH = "health"
    FAMILY_DETAILS = "family_details"
    PERSONAL_URL = "personal_url"
    SALARY = "salary"


OPTIONAL_ENTITY_TYPES: Final = frozenset({EntityType.SALARY})
UNHANDLED_ENTITY_TYPES: Final = frozenset({EntityType.PERSONAL_URL})
MANDATORY_ENTITY_TYPES: Final = (
    frozenset(EntityType) - OPTIONAL_ENTITY_TYPES - UNHANDLED_ENTITY_TYPES
)

REPLACEMENT_LABELS: Final[Mapping[EntityType, str]] = MappingProxyType(
    {
        EntityType.CANDIDATE_NAME: "[NAME]",
        EntityType.REFERENCE_NAME: "[NAME]",
        EntityType.EMAIL: "[EMAIL]",
        EntityType.PHONE: "[PHONE]",
        EntityType.NATIONAL_ID: "[ID]",
        EntityType.PASSPORT: "[ID]",
        EntityType.POSTAL_ADDRESS: "[ADDRESS]",
        EntityType.DATE_OF_BIRTH: "[DOB]",
        EntityType.GENDER: "[REDACTED]",
        EntityType.MARITAL_STATUS: "[REDACTED]",
        EntityType.NATIONALITY: "[REDACTED]",
        EntityType.RELIGION: "[REDACTED]",
        EntityType.ETHNICITY: "[REDACTED]",
        EntityType.HEALTH: "[REDACTED]",
        EntityType.FAMILY_DETAILS: "[REDACTED]",
        EntityType.PERSONAL_URL: "[URL]",
        EntityType.SALARY: "[SALARY]",
    }
)


LABEL_PRIORITY: Final[Mapping[EntityType, int]] = MappingProxyType(
    {
        EntityType.EMAIL: 100,
        EntityType.NATIONAL_ID: 90,
        EntityType.PASSPORT: 85,
        EntityType.DATE_OF_BIRTH: 80,
        EntityType.SALARY: 80,
        EntityType.POSTAL_ADDRESS: 75,
        EntityType.PHONE: 70,
        EntityType.CANDIDATE_NAME: 65,
        EntityType.REFERENCE_NAME: 64,
        EntityType.PERSONAL_URL: 60,
        EntityType.FAMILY_DETAILS: 55,
        EntityType.GENDER: 50,
        EntityType.MARITAL_STATUS: 50,
        EntityType.NATIONALITY: 50,
        EntityType.RELIGION: 50,
        EntityType.ETHNICITY: 50,
        EntityType.HEALTH: 50,
    }
)
"""The more specific type wins an overlap's label (masking-policy.md §5)."""


def label_winner(types: Iterable[EntityType]) -> EntityType:
    """Highest-priority type; ties go to the earlier ``EntityType`` member."""
    order = list(EntityType)
    chosen = sorted(set(types), key=lambda entity: (-LABEL_PRIORITY[entity], order.index(entity)))
    if not chosen:
        raise InvariantError("label_winner needs at least one entity type")
    return chosen[0]


class PolicyAction(StrEnum):
    REDACT = "redact"
    REDACT_AND_REVIEW = "redact_and_review"
    DISCARD = "discard"
    DETECTED_NOT_REDACTED = "detected_not_redacted"


@dataclass(frozen=True, slots=True)
class MaskingPolicy:
    mask_salary: bool = True
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        require_bool(self.mask_salary, "MaskingPolicy.mask_salary")
        if self.version not in KNOWN_POLICY_VERSIONS:
            raise PolicyError("MaskingPolicy.version is not a known policy version")

    @classmethod
    def from_selection(cls, selected: Iterable[EntityType]) -> "MaskingPolicy":
        """Build a policy from an explicit selection; every mandatory type must be present."""
        chosen = frozenset(selected)
        if not all(isinstance(entity, EntityType) for entity in chosen):
            raise PolicyError("selection may only contain EntityType members")
        missing = MANDATORY_ENTITY_TYPES - chosen
        if missing:
            names = ", ".join(sorted(entity.name for entity in missing))
            raise PolicyError(f"mandatory entity types cannot be disabled: {names}")
        return cls(mask_salary=EntityType.SALARY in chosen)

    @property
    def redacted_types(self) -> frozenset[EntityType]:
        if self.mask_salary:
            return MANDATORY_ENTITY_TYPES | OPTIONAL_ENTITY_TYPES
        return MANDATORY_ENTITY_TYPES

    def action_for(self, entity_type: EntityType, confidence: float) -> PolicyAction:
        if not isinstance(entity_type, EntityType):
            raise InvariantError("entity_type must be an EntityType")
        score = require_finite_float(confidence, "confidence")
        if not 0.0 <= score <= 1.0:
            raise InvariantError("confidence must be between 0 and 1")
        if score < DISCARD_THRESHOLD:
            return PolicyAction.DISCARD
        if entity_type not in self.redacted_types:
            return PolicyAction.DETECTED_NOT_REDACTED
        if score >= REDACT_THRESHOLD:
            return PolicyAction.REDACT
        return PolicyAction.REDACT_AND_REVIEW
