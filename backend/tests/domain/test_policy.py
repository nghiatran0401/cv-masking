import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cv_masking.domain.errors import InvariantError, PolicyError
from cv_masking.domain.policy import (
    DISCARD_THRESHOLD,
    MANDATORY_ENTITY_TYPES,
    OPTIONAL_ENTITY_TYPES,
    REDACT_THRESHOLD,
    EntityType,
    MaskingPolicy,
    PolicyAction,
)

EXPECTED_MANDATORY = {
    "candidate_name",
    "reference_name",
    "email",
    "phone",
    "national_id",
    "passport",
    "postal_address",
    "date_of_birth",
    "gender",
    "marital_status",
    "nationality",
    "religion",
    "ethnicity",
    "health",
    "family_details",
    "personal_url",
}


def test_entity_types_and_thresholds_match_the_masking_policy_doc() -> None:
    assert {e.value for e in MANDATORY_ENTITY_TYPES} == EXPECTED_MANDATORY
    assert {EntityType.SALARY} == OPTIONAL_ENTITY_TYPES
    assert (REDACT_THRESHOLD, DISCARD_THRESHOLD) == (0.85, 0.50)
    assert MaskingPolicy().redacted_types == set(EntityType)
    assert MaskingPolicy(mask_salary=False).redacted_types == MANDATORY_ENTITY_TYPES


def test_no_mandatory_type_can_be_disabled() -> None:
    for missing in MANDATORY_ENTITY_TYPES:
        with pytest.raises(PolicyError):
            MaskingPolicy.from_selection(set(EntityType) - {missing})


def test_threshold_boundaries() -> None:
    policy = MaskingPolicy()
    assert policy.action_for(EntityType.EMAIL, math.nextafter(0.50, 0.0)) is PolicyAction.DISCARD
    assert policy.action_for(EntityType.EMAIL, 0.50) is PolicyAction.REDACT_AND_REVIEW
    assert policy.action_for(EntityType.EMAIL, 0.85) is PolicyAction.REDACT
    unmasked = MaskingPolicy(mask_salary=False)
    assert unmasked.action_for(EntityType.SALARY, 0.99) is PolicyAction.DETECTED_NOT_REDACTED


def test_invalid_confidence_is_rejected() -> None:
    for confidence in (math.nan, math.inf, -0.01, 1.01, True, "0.9"):
        with pytest.raises(InvariantError):
            MaskingPolicy().action_for(EntityType.EMAIL, confidence)  # type: ignore[arg-type]


@settings(deadline=None, derandomize=True, database=None)
@given(
    st.sampled_from(sorted(MANDATORY_ENTITY_TYPES)),
    st.floats(min_value=DISCARD_THRESHOLD, max_value=1.0),
    st.booleans(),
)
def test_mandatory_types_above_discard_are_always_redacted(
    entity: EntityType, confidence: float, mask_salary: bool
) -> None:
    action = MaskingPolicy(mask_salary=mask_salary).action_for(entity, confidence)
    assert action in {PolicyAction.REDACT, PolicyAction.REDACT_AND_REVIEW}
