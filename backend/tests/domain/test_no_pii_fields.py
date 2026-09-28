"""Domain objects have no field that could hold document text, and errors never echo values."""

from collections.abc import Callable
from dataclasses import fields
from uuid import uuid4

import pytest
from domain_builders import created, later, new_object_ref, uploaded, validating

from cv_masking.domain.batch import Batch
from cv_masking.domain.document_job import DocumentJob
from cv_masking.domain.errors import DomainError
from cv_masking.domain.findings import (
    BoundingBox,
    DocxLocation,
    DocxRedactionRange,
    EntityFinding,
    FindingCounts,
    PdfLocation,
    RedactionRegion,
)
from cv_masking.domain.ids import BatchId, DocumentId, FindingId, ObjectRef, Sha256Digest
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationResult

EXPECTED_FIELDS: dict[type, tuple[str, ...]] = {
    BatchId: ("value",),
    DocumentId: ("value",),
    FindingId: ("value",),
    ObjectRef: ("value",),
    Sha256Digest: ("value",),
    BoundingBox: ("x0", "y0", "x1", "y1"),
    PdfLocation: ("page_number", "boxes"),
    DocxLocation: ("part_name", "start", "end"),
    EntityFinding: (
        "finding_id",
        "entity_type",
        "location",
        "confidence",
        "detector_id",
        "detector_version",
        "replacement_label",
        "requires_review",
    ),
    RedactionRegion: ("page_number", "boxes", "entity_type", "finding_ids"),
    DocxRedactionRange: ("part_name", "start", "end", "entity_type", "finding_ids"),
    FindingCounts: ("items",),
    MaskingPolicy: ("mask_salary", "version"),
    VerificationResult: (
        "outcome",
        "failure_codes",
        "output_ref",
        "verifier_id",
        "verifier_version",
        "verified_at",
    ),
    Batch: (
        "batch_id",
        "state",
        "mask_salary",
        "document_count",
        "created_at",
        "updated_at",
        "version",
    ),
    DocumentJob: (
        "document_id",
        "batch_id",
        "state",
        "created_at",
        "updated_at",
        "version",
        "document_format",
        "input_ref",
        "content_sha256",
        "size_bytes",
        "uploaded_at",
        "attempt",
        "policy",
        "hidden_removed",
        "findings_review_approved",
        "output_ref",
        "finding_counts",
        "review_reasons",
        "verification",
        "error_code",
    ),
}
# The only str-typed fields; every one is checked against a strict pattern or constant.
STRING_FIELDS = {
    (Sha256Digest, "value"),
    (DocxLocation, "part_name"),
    (DocxRedactionRange, "part_name"),
    (EntityFinding, "detector_id"),
    (EntityFinding, "detector_version"),
    (EntityFinding, "replacement_label"),
    (MaskingPolicy, "version"),
    (VerificationResult, "verifier_id"),
    (VerificationResult, "verifier_version"),
}
MARKER = "Synthetic Candidate Nguyễn 0900000000 synthetic@example.test"


def test_fields_are_exactly_the_allowlist() -> None:
    for cls, expected in EXPECTED_FIELDS.items():
        assert tuple(f.name for f in fields(cls)) == expected, cls.__name__


def test_string_fields_are_exactly_the_validated_set() -> None:
    found = {(cls, f.name) for cls in EXPECTED_FIELDS for f in fields(cls) if f.type is str}
    assert found == STRING_FIELDS


def _attempts() -> list[Callable[[], object]]:
    new, job, checking = created(), uploaded(), validating()
    return [
        lambda: Sha256Digest(MARKER),
        lambda: DocxLocation(MARKER, 0, 1),
        lambda: DocxRedactionRange(MARKER, 0, 1, EntityType.EMAIL, (FindingId(uuid4()),)),
        lambda: MaskingPolicy(version=MARKER),
        lambda: EntityFinding(
            finding_id=MARKER,  # type: ignore[arg-type]
            entity_type=MARKER,  # type: ignore[arg-type]
            location=MARKER,  # type: ignore[arg-type]
            confidence=0.9,
            detector_id=MARKER,
            detector_version=MARKER,
            replacement_label=MARKER,
            requires_review=False,
        ),
        lambda: new.reject_upload(MARKER, later(new)),  # type: ignore[arg-type]
        lambda: checking.fail(MARKER, later(checking)),  # type: ignore[arg-type]
        lambda: checking.validation_needs_review({MARKER}, later(checking)),  # type: ignore[arg-type]
        lambda: job.start_validation(MARKER),  # type: ignore[arg-type]
        lambda: new.mark_uploaded(
            document_format=MARKER,  # type: ignore[arg-type]
            input_ref=new_object_ref(),
            content_sha256=MARKER,  # type: ignore[arg-type]
            size_bytes=1,
            at=later(new),
        ),
    ]


def test_error_messages_never_echo_the_offending_value() -> None:
    for attempt in _attempts():
        with pytest.raises(DomainError) as caught:
            attempt()
        rendered = f"{caught.value}{caught.value!r}{caught.value.args}"
        for fragment in ("Nguyễn", "0900000000", "synthetic@example.test", "Synthetic Candidate"):
            assert fragment not in rendered
