import math
from datetime import datetime
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from domain_builders import T0, new_finding_id, new_object_ref

from cv_masking.domain.codes import ERROR_CODE_GROUPS, CodeGroup, ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import (
    MAX_BOXES_PER_FINDING,
    BoundingBox,
    DocxLocation,
    EntityFinding,
    FindingCounts,
    PdfLocation,
)
from cv_masking.domain.ids import BatchId, DocumentId, FindingId, ObjectRef, Sha256Digest
from cv_masking.domain.policy import REPLACEMENT_LABELS, EntityType
from cv_masking.domain.verification import (
    VERIFY_FAILURE_PRECEDENCE,
    VerificationOutcome,
    VerificationResult,
)

BOX = BoundingBox(10.0, 20.0, 110.0, 32.5)
ID_TYPES = [BatchId, DocumentId, FindingId, ObjectRef]


# ------------------------------------------------------------------ identifiers


@pytest.mark.parametrize("id_type", ID_TYPES)
def test_ids_accept_random_uuids(id_type: type[BatchId]) -> None:
    value = uuid4()
    assert str(id_type(value)) == str(value)


@pytest.mark.parametrize("id_type", ID_TYPES)
@pytest.mark.parametrize(
    "value",
    [NAMESPACE_DNS, uuid5(NAMESPACE_DNS, "synthetic.example"), UUID(int=0), str(uuid4()), None],
    ids=["uuid1", "uuid5", "nil", "string", "none"],
)
def test_ids_reject_non_random_or_untyped_values(id_type: type[BatchId], value: object) -> None:
    with pytest.raises(InvariantError):
        id_type(value)  # type: ignore[arg-type]


def test_distinct_id_types_never_compare_equal() -> None:
    value = uuid4()
    batch_id: object = BatchId(value)
    assert batch_id != DocumentId(value)


def test_digest_accepts_lowercase_sha256_hex() -> None:
    assert str(Sha256Digest("0f" * 32)) == "0f" * 32


@pytest.mark.parametrize(
    "value", ["0F" * 32, "0f" * 31, "0f" * 33, "g" * 64, " " + "0" * 63, b"0" * 64, None]
)
def test_digest_rejects_other_values(value: object) -> None:
    with pytest.raises(InvariantError):
        Sha256Digest(value)  # type: ignore[arg-type]


# ------------------------------------------------------------------ locations


@pytest.mark.parametrize(
    "coords",
    [
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 1.0, 0.0),
        (5.0, 0.0, 1.0, 1.0),
        (math.nan, 0.0, 1.0, 1.0),
        (0.0, math.inf, 1.0, 1.0),
        (True, 0.0, 1.0, 1.0),
        ("0", 0.0, 1.0, 1.0),
    ],
    ids=["zero-width", "zero-height", "inverted", "nan", "inf", "bool", "string"],
)
def test_bounding_box_rejects_degenerate_or_invalid(coords: tuple[object, ...]) -> None:
    with pytest.raises(InvariantError):
        BoundingBox(*coords)  # type: ignore[arg-type]


@pytest.mark.parametrize("page", [1, 30])
def test_pdf_location_accepts_page_bounds(page: int) -> None:
    assert PdfLocation(page, (BOX,)).page_number == page


@pytest.mark.parametrize(
    ("page", "boxes"),
    [
        (0, (BOX,)),
        (31, (BOX,)),
        (1, ()),
        (1, [BOX]),
        (1, (BOX,) * (MAX_BOXES_PER_FINDING + 1)),
        (1, ((10.0, 20.0, 110.0, 32.5),)),
    ],
    ids=["page-0", "page-31", "no-boxes", "list", "too-many", "raw-tuple"],
)
def test_pdf_location_rejects_invalid(page: int, boxes: object) -> None:
    with pytest.raises(InvariantError):
        PdfLocation(page, boxes)  # type: ignore[arg-type]


def test_pdf_location_accepts_the_box_limit() -> None:
    assert len(PdfLocation(1, (BOX,) * MAX_BOXES_PER_FINDING).boxes) == MAX_BOXES_PER_FINDING


@pytest.mark.parametrize(
    "part", ["word/document.xml", "word/header1.xml", "word/footnotes.xml", "word/comments.xml"]
)
def test_docx_location_accepts_word_parts(part: str) -> None:
    assert DocxLocation(part, 0, 5).part_name == part


@pytest.mark.parametrize(
    "part",
    [
        "../word/document.xml",
        "word/../document.xml",
        "/word/document.xml",
        "word/Document.xml",
        "word/document.xml\n",
        "word/_rels/document.xml.rels",
        "customXml/item1.xml",
        "docProps/core.xml",
        "word/media/image1.png",
        "word/" + "a" * 33 + ".xml",
    ],
)
def test_docx_location_rejects_other_parts(part: str) -> None:
    with pytest.raises(InvariantError):
        DocxLocation(part, 0, 5)


@pytest.mark.parametrize(("start", "end"), [(-1, 5), (5, 5), (6, 5), (0, 0), (True, 5)])
def test_docx_location_rejects_empty_or_negative_ranges(start: int, end: int) -> None:
    with pytest.raises(InvariantError):
        DocxLocation("word/document.xml", start, end)


# ------------------------------------------------------------------ findings


def _finding(**changes: object) -> EntityFinding:
    fields: dict[str, object] = {
        "finding_id": new_finding_id(),
        "entity_type": EntityType.EMAIL,
        "location": PdfLocation(1, (BOX,)),
        "confidence": 0.9,
        "detector_id": "regex.email",
        "detector_version": "1.0.0",
        "replacement_label": REPLACEMENT_LABELS[EntityType.EMAIL],
        "requires_review": False,
    }
    fields.update(changes)
    return EntityFinding(**fields)  # type: ignore[arg-type]


def test_finding_accepts_pdf_and_docx_locations() -> None:
    assert _finding().location == PdfLocation(1, (BOX,))
    docx = DocxLocation("word/document.xml", 3, 20)
    assert _finding(location=docx).location == docx


@pytest.mark.parametrize(
    "changes",
    [
        {"finding_id": uuid4()},
        {"entity_type": "email"},
        {"location": (1, (BOX,))},
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"confidence": math.nan},
        {"detector_id": "Nguyen Van A"},
        {"detector_id": "Regex.Email"},
        {"detector_id": "synthetic@example.test"},
        {"detector_id": ""},
        {"detector_version": "1.0"},
        {"detector_version": "v1.0.0"},
        {"replacement_label": "[PHONE]"},
        {"replacement_label": "synthetic.person@example.test"},
        {"requires_review": 0},
    ],
)
def test_finding_rejects_invalid_fields(changes: dict[str, object]) -> None:
    with pytest.raises(InvariantError):
        _finding(**changes)


def test_finding_counts_follow_entity_order() -> None:
    counts = FindingCounts.from_mapping({EntityType.SALARY: 1, EntityType.EMAIL: 2})
    assert counts.items == ((EntityType.EMAIL, 2), (EntityType.SALARY, 1))
    assert counts.as_dict() == {EntityType.EMAIL: 2, EntityType.SALARY: 1}
    assert counts.total == 3
    assert FindingCounts(()).total == 0


@pytest.mark.parametrize(
    "items",
    [
        ((EntityType.SALARY, 1), (EntityType.EMAIL, 2)),
        ((EntityType.EMAIL, 1), (EntityType.EMAIL, 2)),
        ((EntityType.EMAIL, -1),),
        (("email", 1),),
        ((EntityType.EMAIL, 1, 2),),
        [(EntityType.EMAIL, 1)],
    ],
    ids=["out-of-order", "duplicate", "negative", "string-key", "triple", "list"],
)
def test_finding_counts_reject_invalid_items(items: object) -> None:
    with pytest.raises(InvariantError):
        FindingCounts(items)  # type: ignore[arg-type]


# ------------------------------------------------------------------ verification


def _result(**changes: object) -> VerificationResult:
    fields: dict[str, object] = {
        "outcome": VerificationOutcome.PASSED,
        "failure_codes": frozenset(),
        "output_ref": new_object_ref(),
        "verifier_id": "pdf-verifier",
        "verifier_version": "1.0.0",
        "verified_at": T0,
    }
    fields.update(changes)
    return VerificationResult(**fields)  # type: ignore[arg-type]


def test_verification_passed_flag() -> None:
    assert _result().passed is True
    assert _result(outcome=VerificationOutcome.REVIEW_REQUIRED).passed is False


def test_failure_precedence_ranks_every_verify_code_once() -> None:
    verify_codes = {c for c in ErrorCode if ERROR_CODE_GROUPS[c] is CodeGroup.VERIFICATION}
    assert len(VERIFY_FAILURE_PRECEDENCE) == len(set(VERIFY_FAILURE_PRECEDENCE))
    assert set(VERIFY_FAILURE_PRECEDENCE) == verify_codes
    assert VERIFY_FAILURE_PRECEDENCE[:3] == (
        ErrorCode.VERIFY_RESIDUAL_FINDING,
        ErrorCode.VERIFY_RESIDUAL_DETECTION,
        ErrorCode.VERIFY_RESIDUAL_METADATA,
    )


@pytest.mark.parametrize("rank", range(len(VERIFY_FAILURE_PRECEDENCE)))
def test_primary_failure_code_is_the_highest_ranked(rank: int) -> None:
    codes = frozenset(VERIFY_FAILURE_PRECEDENCE[rank:])
    result = _result(outcome=VerificationOutcome.FAILED, failure_codes=codes)
    assert result.primary_failure_code is VERIFY_FAILURE_PRECEDENCE[rank]


def test_non_failed_result_has_no_primary_failure_code() -> None:
    assert _result().primary_failure_code is None


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": VerificationOutcome.FAILED},
        {"failure_codes": frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING})},
        {
            "outcome": VerificationOutcome.FAILED,
            "failure_codes": frozenset({ErrorCode.REDACT_FAILED}),
        },
        {"outcome": VerificationOutcome.FAILED, "failure_codes": {ErrorCode.VERIFY_OUTPUT_INVALID}},
        {"outcome": "passed"},
        {"output_ref": uuid4()},
        {"verifier_id": "Verifier For Nguyen"},
        {"verifier_version": "latest"},
        {"verified_at": datetime(2026, 1, 1)},
    ],
    ids=[
        "failed-without-codes",
        "passed-with-codes",
        "non-verify-code",
        "set-codes",
        "string-outcome",
        "raw-uuid-ref",
        "free-text-verifier",
        "non-semver",
        "naive-time",
    ],
)
def test_verification_rejects_invalid_fields(changes: dict[str, object]) -> None:
    with pytest.raises(InvariantError):
        _result(**changes)
