"""Stage 10b: synthetic DOCX → extraction → detection → redaction → reopen.

Checks are computed into booleans or counts first, so a failure prints no
fixture text. Messages carry case indexes, categories, and entity types only.
"""

import io
import logging
from collections import Counter
from uuid import uuid4

import docx
import pytest
from synthetic_docx_redaction import (
    AUTHOR,
    BODY,
    BOX_TEXT,
    EMAIL,
    HIDDEN,
    HIDDEN_BUILDERS,
    MEDIA,
    PHONE,
    SALARY,
    STYLES,
    appears,
    base_parts,
    cv_docx,
    decompressed,
    pack,
    para,
    run,
    with_hidden,
)

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.docx import DocxExtractor, DocxXmlRedactor
from cv_masking.adapters.docx import redactor as docx_redactor
from cv_masking.adapters.docx.text import parse_xml
from cv_masking.adapters.docx.xmledit import XmlPart
from cv_masking.application import DetectionOutcome, DetectionService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import DocxRedactionRange
from cv_masking.domain.ids import FindingId
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.ports.extraction import ExtractedDocument

_NAME_PIECES = ("Nguyễn Văn", "Mẫu")
_DOCUMENT = "word/document.xml"


def _extract(data: bytes) -> ExtractedDocument:
    result = DocxExtractor().extract(data)
    assert result.document is not None
    return result.document


def _detect(data: bytes, policy: MaskingPolicy | None = None) -> DetectionOutcome:
    outcome = DetectionService(PresidioDetector()).detect(_extract(data), policy or MaskingPolicy())
    assert outcome.failure is None
    return outcome


def _ranges(policy: MaskingPolicy | None = None) -> tuple[DocxRedactionRange, ...]:
    """Ranges detected on the base CV; hidden builders only append after them."""
    return _detect(cv_docx(), policy).docx_ranges


def _redact(
    data: bytes, ranges: tuple[DocxRedactionRange, ...], *, remove_hidden: bool = False
) -> bytes:
    result = DocxXmlRedactor().redact(data, ranges, remove_hidden=remove_hidden)
    assert result.failure is None, result.failure
    assert result.output is not None
    return result.output


def _text(data: bytes) -> str:
    return "\n".join(part.text for part in _extract(data).parts)


def _manual(start: int, end: int, part: str = _DOCUMENT) -> DocxRedactionRange:
    return DocxRedactionRange(part, start, end, EntityType.CANDIDATE_NAME, (FindingId(uuid4()),))


def test_detected_values_are_absent_from_every_part() -> None:
    data = cv_docx()
    outcome = _detect(data)
    found = Counter(item.entity_type for item in outcome.docx_ranges)
    assert found[EntityType.CANDIDATE_NAME] == 1
    assert found[EntityType.EMAIL] == 2
    assert found[EntityType.PHONE] == 2
    assert found[EntityType.SALARY] == 1
    output = _redact(data, outcome.docx_ranges)
    for index, value in enumerate((*_NAME_PIECES, EMAIL, PHONE, SALARY)):
        before, after = appears(value, data), appears(value, output)
        assert before, f"value {index} missing from the fixture"
        assert not after, f"value {index} still in a decompressed part"
    text = _text(output)
    for label in ("[NAME]", "[EMAIL]", "[PHONE]", "[SALARY]"):
        assert label in text, label


def test_the_label_keeps_the_formatting_of_the_first_redacted_run() -> None:
    output = _redact(cv_docx(), _ranges())
    runs = [
        item
        for paragraph in docx.Document(io.BytesIO(output)).paragraphs
        for item in paragraph.runs
    ]
    labelled = [index for index, item in enumerate(runs) if item.text == "[NAME]"]
    assert len(labelled) == 1
    first = runs[labelled[0]]
    following = runs[labelled[0] + 1]
    assert first.italic is True
    assert following.text == ""
    assert following.bold is True


def test_unredacted_text_and_structure_survive() -> None:
    data = cv_docx()
    output = _redact(data, _ranges())
    text = _text(output)
    for index, kept in enumerate(
        (BODY, "Họ và tên:", "Email:", "Kỹ năng", "Python", "profile link")
    ):
        assert kept in text, f"kept text {index} missing"
    before, after = docx.Document(io.BytesIO(data)), docx.Document(io.BytesIO(output))
    assert len(after.paragraphs) == len(before.paragraphs)
    assert len(after.tables) == len(before.tables) == 1
    assert after.tables[0].cell(0, 1).text == "Python"


def test_namespace_prefixes_and_unrelated_parts_are_preserved() -> None:
    data = cv_docx()
    source, output = decompressed(data), decompressed(_redact(data, _ranges()))
    head = source[_DOCUMENT].split(b"<w:body>")[0]
    assert output[_DOCUMENT].startswith(head)
    assert b'mc:Ignorable="w14"' in output[_DOCUMENT]
    assert output["word/styles.xml"] == STYLES.encode()
    assert output["word/media/image1.png"] == MEDIA
    assert next(iter(output)) == "[Content_Types].xml"


def test_redaction_never_adds_an_element() -> None:
    data = cv_docx()
    source, output = decompressed(data), decompressed(_redact(data, _ranges()))
    for name in (_DOCUMENT, "word/header1.xml", "word/footnotes.xml"):
        before = Counter(element.tag for element in parse_xml(source[name]).iter())
        after = Counter(element.tag for element in parse_xml(output[name]).iter())
        added = after - before
        assert not added, name


def test_choice_and_fallback_copies_are_redacted_together() -> None:
    data = cv_docx()
    text = _extract(data).parts[0].text
    start = text.index(BOX_TEXT)
    output = _redact(data, (_manual(start, start + len(BOX_TEXT)),))
    left = appears(BOX_TEXT, output)
    assert not left
    choice, fallback = decompressed(output)[_DOCUMENT].split(b"<mc:Fallback>")
    assert b"[NAME]" in choice.split(b"<mc:Choice")[1]
    assert b"[NAME]" in fallback


def test_salary_is_redacted_only_when_the_toggle_is_on() -> None:
    data = cv_docx()
    masked = _redact(data, _ranges(MaskingPolicy(mask_salary=True)))
    unmasked = _redact(data, _ranges(MaskingPolicy(mask_salary=False)))
    in_masked, in_unmasked = appears(SALARY, masked), appears(SALARY, unmasked)
    assert not in_masked
    assert in_unmasked
    email_kept = appears(EMAIL, unmasked)
    assert not email_kept


def test_always_stripped_items_are_removed_without_approval() -> None:
    data = cv_docx()
    present = [appears(AUTHOR, data), appears(f"mailto:{EMAIL}", data)]
    assert all(present)
    output = _redact(data, ())
    parts = decompressed(output)
    for name in (
        "docProps/core.xml",
        "docProps/app.xml",
        "docProps/thumbnail.jpeg",
        "word/people.xml",
    ):
        assert name not in parts, name
    for index, value in enumerate((AUTHOR, f"mailto:{EMAIL}", "HYPERLINK mailto")):
        leaked = appears(value, output)
        assert not leaked, f"stripped value {index} still in the package"
    raw = b"".join(parts.values())
    for marker in (
        b"rsid",
        b"instrText",
        b"docVar",
        b"tooltip",
        b"descr=",
        b'TargetMode="External"',
    ):
        assert marker not in raw, marker
    assert b"<w:hyperlink>" in parts[_DOCUMENT]
    types = parts["[Content_Types].xml"]
    assert b"/docProps/core.xml" not in types
    assert b"/word/people.xml" not in types


@pytest.mark.parametrize("category", sorted(HIDDEN_BUILDERS))
def test_each_hidden_category_is_removed_when_approved(category: str) -> None:
    data = with_hidden(category)
    classified = DocxExtractor().extract(data)
    assert classified.review == {ReviewReason.DOCX_HIDDEN_CONTENT}, category
    present = appears(HIDDEN, data)
    assert present, category
    output = _redact(data, _ranges(), remove_hidden=True)
    leaked = appears(HIDDEN, output)
    assert not leaked, category
    reopened = DocxExtractor().extract(output)
    assert reopened.document is not None, category
    text = "\n".join(part.text for part in reopened.document.parts)
    assert BODY in text, category
    assert "[NAME]" in text, category
    name_left = any(appears(piece, output) for piece in _NAME_PIECES)
    assert not name_left, category


def test_all_hidden_categories_are_removed_together() -> None:
    output = _redact(with_hidden(*HIDDEN_BUILDERS), _ranges(), remove_hidden=True)
    leaked = appears(HIDDEN, output)
    assert not leaked
    parts = decompressed(output)
    dropped = [
        name
        for name in parts
        if name.startswith(("customXml/", "word/embeddings/", "word/glossary/", "word/comments"))
        or name == "word/afchunk.htm"
    ]
    assert dropped == []
    assert DocxExtractor().extract(output).document is not None


def test_tracked_changes_are_accepted() -> None:
    output = _redact(with_hidden("tracked_changes"), _ranges(), remove_hidden=True)
    assert "Inserted line" in _text(output)
    document = decompressed(output)[_DOCUMENT]
    assert b"<w:ins" not in document
    assert b"<w:del" not in document


@pytest.mark.parametrize("category", sorted(HIDDEN_BUILDERS))
def test_hidden_content_without_approval_is_refused(category: str) -> None:
    result = DocxXmlRedactor().redact(with_hidden(category), _ranges(), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_SANITIZE_FAILED, category
    assert result.output is None


def test_input_bytes_are_never_modified() -> None:
    data = cv_docx()
    copy = bytes(bytearray(data))
    _redact(data, _ranges())
    assert data == copy


@pytest.mark.parametrize(
    "data",
    [b"", b"not a zip", bytes.fromhex("d0cf11e0a1b11ae1") + b"synthetic-ole"],
    ids=["empty", "garbage", "encrypted"],
)
def test_unreadable_input_fails_closed(data: bytes) -> None:
    result = DocxXmlRedactor().redact(data, (), remove_hidden=True)
    assert result.failure is ErrorCode.REDACT_FAILED


@pytest.mark.parametrize(
    "unit",
    [_manual(0, 3, "word/header9.xml"), _manual(0, 3, "word/settings.xml"), _manual(0, 10_000)],
    ids=["missing-part", "not-a-text-part", "past-the-end"],
)
def test_a_range_that_cannot_be_placed_fails(unit: DocxRedactionRange) -> None:
    result = DocxXmlRedactor().redact(cv_docx(), (unit,), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED


def test_a_combining_mark_that_starts_a_run_keeps_offsets_aligned() -> None:
    parts = base_parts()
    parts[_DOCUMENT] = str(parts[_DOCUMENT]).replace(
        "<!--body-->", para(run("Ma"), run("\u0303u Tail")) + "<!--body-->"
    )
    data = pack(parts)
    text = _extract(data).parts[0].text
    start = text.index("Ma\u0303u")
    output = _redact(data, (_manual(start, start + 4),))
    redacted = _extract(output).parts[0].text
    assert "[NAME] Tail" in redacted
    assert "\u0303" not in redacted


def test_a_utf16_part_fails_closed() -> None:
    parts = base_parts()
    parts["word/header1.xml"] = (
        str(parts["word/header1.xml"])
        .replace('encoding="UTF-8"', 'encoding="UTF-16"')
        .encode("utf-16")
    )
    result = DocxXmlRedactor().redact(pack(parts), _ranges(), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED


def test_text_left_in_place_fails_the_output_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(XmlPart, "set_text", lambda self, element, text: None)
    result = DocxXmlRedactor().redact(cv_docx(), _ranges(), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED


def test_skipped_stripping_fails_the_output_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def keep(part: XmlPart, *, text_part: bool) -> None:
        del part, text_part

    monkeypatch.setattr(docx_redactor, "_strip_part", keep)
    result = DocxXmlRedactor().redact(cv_docx(), _ranges(), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_SANITIZE_FAILED


def test_redaction_logs_nothing_from_the_document(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        _redact(with_hidden(*HIDDEN_BUILDERS), _ranges(), remove_hidden=True)
    logged = " ".join(record.getMessage() for record in caplog.records)
    for index, value in enumerate((*_NAME_PIECES, EMAIL, PHONE, SALARY, AUTHOR, HIDDEN)):
        found = value in logged
        assert not found, f"value {index} logged"
