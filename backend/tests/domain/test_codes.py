"""The code enums and docs/error-codes.md describe the same closed sets."""

import re
from pathlib import Path

from cv_masking.domain.codes import (
    ERROR_CODE_GROUPS,
    RETRYABLE_ERROR_CODES,
    REVIEW_REASON_KINDS,
    ErrorCode,
    ReviewReason,
)
from cv_masking.domain.verification import VERIFY_FAILURE_PRECEDENCE

DOC = Path(__file__).resolve().parents[3] / "docs" / "error-codes.md"
_CODE_ROW = re.compile(r"^\| `([A-Z0-9_]+)` \| (R|T|—) \|", re.MULTILINE)
_REASON_ROW = re.compile(r"^\| `([A-Z0-9_]+)` \| (blocking|findings|verifier) \|", re.MULTILINE)


def _doc_sections() -> tuple[str, str]:
    states, codes = DOC.read_text(encoding="utf-8").split("\n## 3. Codes\n", maxsplit=1)
    return states, codes


def test_codes_and_reasons_match_the_doc() -> None:
    rows = _CODE_ROW.findall(_doc_sections()[1])
    names = [name for name, _ in rows]
    assert len(names) == len(set(names))
    assert {n for n, kind in rows if kind in {"R", "T"}} == {c.value for c in ErrorCode}
    assert {n for n, kind in rows if kind == "R"} == {c.value for c in RETRYABLE_ERROR_CODES}
    assert {n for n, kind in rows if kind == "—"} == {r.value for r in ReviewReason}
    kinds = dict(_REASON_ROW.findall(_doc_sections()[0]))
    assert kinds == {reason.value: kind.value for reason, kind in REVIEW_REASON_KINDS.items()}


def test_verification_precedence_matches_the_doc() -> None:
    paragraph = _doc_sections()[1].split("(`VERIFY_FAILURE_PRECEDENCE`):", 1)[1].split(". ", 1)[0]
    documented = tuple(re.findall(r"`([A-Z_]+)`", paragraph))
    assert documented == tuple(code.value for code in VERIFY_FAILURE_PRECEDENCE)


def test_every_code_has_a_group() -> None:
    assert set(ERROR_CODE_GROUPS) == set(ErrorCode)
