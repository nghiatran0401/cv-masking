"""The code enums and docs/error-codes.md describe the same closed sets."""

import re
from collections import Counter
from pathlib import Path

import pytest

from cv_masking.domain.codes import (
    ERROR_CODE_GROUPS,
    RETRYABLE_ERROR_CODES,
    REVIEW_REASON_KINDS,
    CodeGroup,
    ErrorCode,
    ReviewKind,
    ReviewReason,
    error_format,
    is_retryable,
    reason_format,
)
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.verification import VERIFY_FAILURE_PRECEDENCE

DOC = Path(__file__).resolve().parents[3] / "docs" / "error-codes.md"
_CODE_ROW = re.compile(r"^\| `([A-Z0-9_]+)` \| (R|T|—) \|", re.MULTILINE)
_REASON_ROW = re.compile(
    r"^\| `([A-Z0-9_]+)` \| (blocking|hidden_content|findings|verifier) \|", re.MULTILINE
)


def _doc_sections() -> tuple[str, str]:
    text = DOC.read_text(encoding="utf-8")
    states, codes = text.split("\n## 3. Codes\n", maxsplit=1)
    return states, codes


def _code_rows() -> list[tuple[str, str]]:
    return _CODE_ROW.findall(_doc_sections()[1])


def test_codes_table_lists_each_code_once() -> None:
    duplicates = [name for name, n in Counter(name for name, _ in _code_rows()).items() if n > 1]
    assert duplicates == []


def test_error_codes_match_the_doc() -> None:
    documented = {name for name, kind in _code_rows() if kind in {"R", "T"}}
    assert documented == {code.value for code in ErrorCode}


def test_retryable_codes_match_the_doc() -> None:
    documented = {name for name, kind in _code_rows() if kind == "R"}
    assert documented == {code.value for code in RETRYABLE_ERROR_CODES}


def test_review_reasons_match_the_doc() -> None:
    documented = {name for name, kind in _code_rows() if kind == "—"}
    assert documented == {reason.value for reason in ReviewReason}


def test_review_reason_kinds_match_the_doc() -> None:
    rows = _REASON_ROW.findall(_doc_sections()[0])
    assert len(rows) == len(ReviewReason)
    assert dict(rows) == {reason.value: kind.value for reason, kind in REVIEW_REASON_KINDS.items()}


def test_verification_precedence_matches_the_doc() -> None:
    paragraph = _doc_sections()[1].split("(`VERIFY_FAILURE_PRECEDENCE`):", 1)[1].split(". ", 1)[0]
    documented = tuple(re.findall(r"`([A-Z_]+)`", paragraph))
    assert documented == tuple(code.value for code in VERIFY_FAILURE_PRECEDENCE)


def test_error_codes_and_review_reasons_are_disjoint() -> None:
    assert not {c.value for c in ErrorCode} & {r.value for r in ReviewReason}


@pytest.mark.parametrize("code", list(ErrorCode))
def test_code_value_is_its_name(code: ErrorCode) -> None:
    assert code.value == code.name
    assert re.fullmatch(r"[A-Z][A-Z0-9_]+", code.value)


def test_every_code_has_a_group() -> None:
    assert set(ERROR_CODE_GROUPS) == set(ErrorCode)
    assert ERROR_CODE_GROUPS[ErrorCode.DOCX_MACRO_OR_TEMPLATE] is CodeGroup.UPLOAD
    assert ERROR_CODE_GROUPS[ErrorCode.DOCX_MALFORMED] is CodeGroup.VALIDATION
    assert ERROR_CODE_GROUPS[ErrorCode.INTERNAL_ERROR] is CodeGroup.INTERNAL


def test_code_groups_are_read_only() -> None:
    with pytest.raises(TypeError):
        ERROR_CODE_GROUPS[ErrorCode.INTERNAL_ERROR] = CodeGroup.UPLOAD  # type: ignore[index]


def test_is_retryable() -> None:
    assert is_retryable(ErrorCode.JOB_INTERRUPTED)
    assert not is_retryable(ErrorCode.JOB_EXPIRED)


def test_every_reason_has_a_kind() -> None:
    assert set(REVIEW_REASON_KINDS) == set(ReviewReason)
    assert set(REVIEW_REASON_KINDS.values()) == set(ReviewKind)


@pytest.mark.parametrize(
    ("code", "fmt"),
    [
        (ErrorCode.PDF_MALFORMED, DocumentFormat.PDF),
        (ErrorCode.DOCX_UNSAFE_ARCHIVE, DocumentFormat.DOCX),
        (ErrorCode.VERIFY_PAGE_COUNT_MISMATCH, DocumentFormat.PDF),
        (ErrorCode.VERIFY_STRUCTURE_MISMATCH, DocumentFormat.DOCX),
        (ErrorCode.DOCX_MACRO_OR_TEMPLATE, None),
        (ErrorCode.VERIFY_RESIDUAL_FINDING, None),
        (ErrorCode.INTERNAL_ERROR, None),
    ],
)
def test_error_format(code: ErrorCode, fmt: DocumentFormat | None) -> None:
    assert error_format(code) is fmt


def test_reason_format() -> None:
    assert reason_format(ReviewReason.PDF_HIDDEN_CONTENT) is DocumentFormat.PDF
    assert reason_format(ReviewReason.DOCX_NO_TEXT) is DocumentFormat.DOCX
    assert reason_format(ReviewReason.DETECT_LOW_CONFIDENCE) is None
