import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cv_masking.domain.errors import InvariantError, PolicyError
from cv_masking.domain.policy import (
    DISCARD_THRESHOLD,
    MANDATORY_ENTITY_TYPES,
    OPTIONAL_ENTITY_TYPES,
    POLICY_VERSION,
    REDACT_THRESHOLD,
    REPLACEMENT_LABELS,
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


def test_policy_constants_match_masking_policy_doc() -> None:
    assert POLICY_VERSION == "1"
    assert REDACT_THRESHOLD == 0.85
    assert DISCARD_THRESHOLD == 0.50


def test_entity_types_are_the_approved_list() -> None:
    assert {e.value for e in MANDATORY_ENTITY_TYPES} == EXPECTED_MANDATORY
    assert {EntityType.SALARY} == OPTIONAL_ENTITY_TYPES
    assert set(EntityType) == MANDATORY_ENTITY_TYPES | OPTIONAL_ENTITY_TYPES


def test_every_type_has_a_bracketed_label() -> None:
    assert set(REPLACEMENT_LABELS) == set(EntityType)
    for label in REPLACEMENT_LABELS.values():
        assert label.startswith("[")
        assert label.endswith("]")
        assert label[1:-1].isupper()


def test_default_policy_redacts_everything() -> None:
    assert MaskingPolicy().redacted_types == set(EntityType)


def test_salary_toggle_only_removes_salary() -> None:
    assert MaskingPolicy(mask_salary=False).redacted_types == MANDATORY_ENTITY_TYPES


@pytest.mark.parametrize("missing", sorted(MANDATORY_ENTITY_TYPES))
def test_mandatory_type_cannot_be_disabled(missing: EntityType) -> None:
    with pytest.raises(PolicyError):
        MaskingPolicy.from_selection(set(EntityType) - {missing})


def test_selection_sets_the_salary_toggle() -> None:
    assert MaskingPolicy.from_selection(MANDATORY_ENTITY_TYPES).mask_salary is False
    assert MaskingPolicy.from_selection(set(EntityType)).mask_salary is True


def test_selection_rejects_unknown_types() -> None:
    with pytest.raises(PolicyError):
        MaskingPolicy.from_selection([*EntityType, "photo"])  # type: ignore[list-item]


def test_unknown_policy_version_is_rejected() -> None:
    with pytest.raises(PolicyError):
        MaskingPolicy(version="2")


def test_non_bool_salary_toggle_is_rejected() -> None:
    with pytest.raises(InvariantError):
        MaskingPolicy(mask_salary=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("confidence", "action"),
    [
        (0.0, PolicyAction.DISCARD),
        (math.nextafter(0.50, 0.0), PolicyAction.DISCARD),
        (0.50, PolicyAction.REDACT_AND_REVIEW),
        (math.nextafter(0.85, 0.0), PolicyAction.REDACT_AND_REVIEW),
        (0.85, PolicyAction.REDACT),
        (1.0, PolicyAction.REDACT),
        (1, PolicyAction.REDACT),
    ],
)
def test_threshold_boundaries(confidence: float, action: PolicyAction) -> None:
    assert MaskingPolicy().action_for(EntityType.EMAIL, confidence) is action


@pytest.mark.parametrize(
    ("confidence", "action"),
    [
        (0.49, PolicyAction.DISCARD),
        (0.50, PolicyAction.DETECTED_NOT_REDACTED),
        (0.99, PolicyAction.DETECTED_NOT_REDACTED),
    ],
)
def test_unmasked_salary_is_reported_but_not_redacted(
    confidence: float, action: PolicyAction
) -> None:
    policy = MaskingPolicy(mask_salary=False)
    assert policy.action_for(EntityType.SALARY, confidence) is action


@pytest.mark.parametrize(
    "confidence", [math.nan, math.inf, -math.inf, -0.01, 1.01, True, "0.9", None]
)
def test_invalid_confidence_is_rejected(confidence: object) -> None:
    with pytest.raises(InvariantError):
        MaskingPolicy().action_for(EntityType.EMAIL, confidence)  # type: ignore[arg-type]


def test_action_requires_an_entity_type() -> None:
    with pytest.raises(InvariantError):
        MaskingPolicy().action_for("email", 0.9)  # type: ignore[arg-type]


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
