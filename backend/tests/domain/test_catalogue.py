"""The catalogue is the edit surface for fields and patterns."""

from cv_masking.domain.catalogue import (
    ANYWHERE_PATTERNS,
    EMAIL_LOCAL_RE,
    EMAIL_RE,
    FIELDS,
    LABELED_VALUE_KIND,
)
from cv_masking.domain.policy import (
    OPTIONAL_ENTITY_TYPES,
    REPLACEMENT_LABELS,
    UNHANDLED_ENTITY_TYPES,
    EntityType,
)


def test_salary_is_the_editable_field_and_labels_come_from_the_catalogue() -> None:
    editable = tuple(field for field in FIELDS if field.editable)
    assert len(editable) == 1
    assert editable[0].entity == EntityType.SALARY.value
    assert editable[0].replacement == "[SALARY]"
    assert frozenset({EntityType.SALARY}) == OPTIONAL_ENTITY_TYPES
    assert frozenset({EntityType.PERSONAL_URL}) == UNHANDLED_ENTITY_TYPES
    assert {EntityType(field.entity): field.replacement for field in FIELDS} == REPLACEMENT_LABELS


def test_email_capture_stays_aligned_with_the_email_pattern() -> None:
    assert EMAIL_RE.replace(
        r"[A-Za-z0-9._%+\-]+@",
        r"([A-Za-z0-9._%+\-]+)@",
        1,
    ) == EMAIL_LOCAL_RE


def test_applied_patterns_name_catalogue_fields() -> None:
    known = {field.entity for field in FIELDS}
    assert {pattern.entity for pattern in ANYWHERE_PATTERNS} <= known
    assert set(LABELED_VALUE_KIND) <= known
