"""Section-based family details and unlabeled contact-block addresses."""

import re
from typing import Final

from cv_masking.adapters.detection.hits import Hit
from cv_masking.adapters.detection.normalize import fold
from cv_masking.adapters.detection.sections import PartView, SectionKind
from cv_masking.domain.policy import EntityType

FAMILY_CONFIDENCE: Final = 0.90
_CONTACT_LINES: Final = 15
_SEGMENT_RE: Final = re.compile(r"\||•|·|;|\s[-\u2013\u2014]\s|\t")
_TOKEN_RE: Final = re.compile(r"[a-z]+\.?")
_PHONE_LIKE_RE: Final = re.compile(r"(?:\d[\s.\-]?){9,}")
ADDRESS_CUES: Final = frozenset(
    {
        "so",
        "duong",
        "pho",
        "ngo",
        "ngach",
        "hem",
        "kiet",
        "phuong",
        "quan",
        "huyen",
        "xa",
        "tinh",
        "thon",
        "ap",
        "khu",
        "street",
        "st",
        "road",
        "rd",
        "avenue",
        "ave",
        "lane",
        "ward",
        "district",
        "dist",
        "province",
        "apartment",
    }
)
_ABBREVIATED_CUES: Final = frozenset({"p.", "q.", "tp.", "tx.", "tt."})
_NUMBERED_CUE_RES: Final = (
    re.compile(r"\bbuilding\s+\d{1,4}\b", re.I),
    re.compile(r"\bfloor\s+\d{1,3}\b", re.I),
    re.compile(r"\b\d{1,3}(?:st|nd|rd|th)\s+floor\b", re.I),
    re.compile(r"\bapt\.?\s+\d{1,4}\b", re.I),
)
_AGE_OR_YEAR_RE: Final = re.compile(r"\b\d{1,2}\s+years?\b|\b(?:19|20)\d{2}\b", re.I)


def family_hits(view: PartView) -> list[Hit]:
    """The whole content block after a family heading, up to the next heading."""
    hits: list[Hit] = []
    for start, end in view.ranges(SectionKind.FAMILY):
        while end > start and view.text[end - 1].isspace():
            end -= 1
        while start < end and view.text[start].isspace():
            start += 1
        if end > start:
            hits.append(
                Hit(
                    EntityType.FAMILY_DETAILS,
                    start,
                    end,
                    FAMILY_CONFIDENCE,
                    "family.section",
                    ("section_heading",),
                )
            )
    return hits


def contact_address_hits(view: PartView) -> list[Hit]:
    """Address-shaped segments in the contact block before the first section heading."""
    hits: list[Hit] = []
    for line in view.lines[: min(view.first_heading, _CONTACT_LINES)]:
        raw = view.text[line.start : line.end]
        cursor = 0
        for piece in _SEGMENT_RE.split(raw):
            offset = raw.find(piece, cursor)
            if offset < 0 or not piece.strip():
                continue
            cursor = offset + len(piece)
            hit = _address_segment(piece, line.start + offset)
            if hit is not None:
                hits.append(hit)
    return hits


def _address_segment(segment: str, absolute: int) -> Hit | None:
    if ":" in segment or "@" in segment or _PHONE_LIKE_RE.search(segment):
        return None
    tokens = _TOKEN_RE.findall(fold(segment))
    cues = {token.rstrip(".") for token in tokens if token.rstrip(".") in ADDRESS_CUES}
    cues |= {token for token in tokens if token in _ABBREVIATED_CUES}
    if any(pattern.search(segment) for pattern in _NUMBERED_CUE_RES):
        cues.add("numbered_site")
    has_number = _has_house_number(segment)
    confidence: float
    signals: tuple[str, ...]
    if len(cues) >= 2 and has_number:
        confidence, signals = 0.88, ("contact_block", "address_cues", "house_number")
    elif len(cues) >= 2:
        confidence, signals = 0.75, ("contact_block", "address_cues")
    elif len(cues) == 1 and has_number:
        confidence, signals = 0.70, ("contact_block", "address_cues", "house_number")
    else:
        return None
    stripped = segment.strip()
    start = absolute + segment.index(stripped)
    return Hit(
        EntityType.POSTAL_ADDRESS,
        start,
        start + len(stripped),
        confidence,
        "address.contact_block",
        signals,
    )


def _has_house_number(segment: str) -> bool:
    """Digits that look like a street number, not '6 years' or a calendar year."""
    return any(char.isdigit() for char in _AGE_OR_YEAR_RE.sub(" ", segment))
