"""Security review: detection stays near-linear on long adversarial lines.

Each shape used to take 20 s or more at these lengths (quadratic regex backtracking).
Test ids and assertion messages carry shape indexes and timings only.
"""

import time

import pytest
from synthetic_names import EN_EMAIL, VN_EMAIL, docx, span_of

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.application import DetectionService
from cv_masking.domain.policy import EntityType, MaskingPolicy

_BUDGET_SECONDS = 5.0
_N = 100_000

_SHAPES: tuple[str, ...] = (
    " " * _N + "x",
    "Kinh nghiệm" + " " * _N + "x",
    "\t" * _N + "x",
    "a" * _N,
    "1" * _N,
    "1." * (_N // 2),
    "1 " * (_N // 2),
    "a._%+-" * (_N // 6),
    "a@" + "b" * _N,
    "a@" + "b." * (2 * _N),
    "a@b." * (_N // 4),
    "1,000 " * (_N // 6),
    "Ab " * (_N // 3),
    "Địa chỉ: " + "ă " * (_N // 2),
    "Tên - " * (_N // 6),
)


@pytest.mark.parametrize("line", _SHAPES, ids=[f"shape{index}" for index in range(len(_SHAPES))])
def test_long_adversarial_line_finishes_within_budget(line: str) -> None:
    service = DetectionService(PresidioDetector())
    started = time.perf_counter()
    service.detect(docx(line, "Kỹ năng"), MaskingPolicy())
    elapsed = time.perf_counter() - started
    assert elapsed < _BUDGET_SECONDS, f"took {elapsed:.1f}s"


_EMAIL_CONTEXTS: tuple[str, ...] = (
    "Email: {}",
    "Email: {}.",
    "Liên hệ {}, hoặc điện thoại",
    "Email:{};",
    "({})",
    "Email: {}-cv",
)


@pytest.mark.parametrize(
    "template", _EMAIL_CONTEXTS, ids=[f"context{index}" for index in range(len(_EMAIL_CONTEXTS))]
)
@pytest.mark.parametrize("email", [VN_EMAIL, EN_EMAIL], ids=["vn", "en"])
def test_bounded_email_pattern_still_matches_the_whole_address(template: str, email: str) -> None:
    line = template.format(email)
    outcome = DetectionService(PresidioDetector()).detect(docx(line), MaskingPolicy())
    spans = {
        (match.start, match.end)
        for match in outcome.matches
        if match.entity_type is EntityType.EMAIL
    }
    assert spans == {span_of(line, email)}, "email span differs"
