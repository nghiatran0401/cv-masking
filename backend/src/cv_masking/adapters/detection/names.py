"""Explainable candidate and reference name heuristics. No models, no remote calls.

Every hit carries signals naming the rules that fired. A name found without an
explicit label and without a strong layout or email signal stays below the
redact threshold, so the document goes to review.
"""

import re
import statistics
from dataclasses import dataclass
from typing import Final

from cv_masking.adapters.detection.hits import Hit
from cv_masking.adapters.detection.normalize import fold, fold_with_map, original_span
from cv_masking.adapters.detection.sections import PartView, SectionKind, is_heading_text
from cv_masking.domain.policy import EntityType

LABELED: Final = 0.95
LABEL_SHAPE_MISMATCH: Final = 0.75
HONORIFIC: Final = 0.90
REFERENCE_LINE: Final = 0.75
_HEADER_BASE: Final = 0.55
_HEADER_CAP: Final = 0.95
_HEADER_LINES: Final = 6
_LARGE_FONT_RATIO: Final = 1.25

NAME_LABELS: Final = (
    "ho va ten",
    "ho ten",
    "ten ung vien",
    "ten",
    "full name",
    "candidate name",
    "name",
)
HONORIFICS: Final = ("ong", "ba", "anh", "chi", "co", "thay", "mr", "mrs", "ms", "miss", "dr")
VN_SURNAMES: Final = frozenset(
    {
        "nguyen",
        "tran",
        "le",
        "pham",
        "hoang",
        "huynh",
        "phan",
        "vu",
        "vo",
        "dang",
        "bui",
        "do",
        "ho",
        "ngo",
        "duong",
        "ly",
        "dinh",
        "truong",
        "mai",
        "to",
        "lam",
        "ha",
        "dao",
        "cao",
        "luu",
        "ta",
        "chau",
        "quach",
        "thai",
        "kieu",
        "chu",
        "trieu",
        "luong",
        "doan",
        "trinh",
        "tang",
    }
)
EXCLUDED_TOKENS: Final = frozenset(
    {
        "ltd",
        "inc",
        "corp",
        "jsc",
        "llc",
        "plc",
        "bank",
        "group",
        "company",
        "corporation",
        "holdings",
        "limited",
        "university",
        "college",
        "institute",
        "academy",
        "school",
        "technology",
        "technologies",
        "solutions",
        "software",
        "services",
        "consulting",
        "vitae",
        "resume",
        "cv",
        "engineer",
        "developer",
        "manager",
        "analyst",
        "intern",
        "specialist",
        "officer",
        "director",
        "consultant",
        "designer",
        "accountant",
        "executive",
        "assistant",
        "lead",
        "head",
        "senior",
        "junior",
        "tnhh",
    }
)
EXCLUDED_PHRASES: Final = (
    "cong ty",
    "co phan",
    "ngan hang",
    "dai hoc",
    "cao dang",
    "hoc vien",
    "truong dai",
    "truong thpt",
    "truong thcs",
    "thanh pho",
    "ho chi minh",
    "ha noi",
    "da nang",
    "hai phong",
    "can tho",
    "viet nam",
    "vietnam",
    "curriculum vitae",
    "so yeu ly lich",
    "ho so",
    "chuyen vien",
    "nhan vien",
    "ky su",
    "truong phong",
    "giam doc",
    "ke toan",
    "thuc tap",
)
_WEAK_EMAIL_TOKENS: Final = frozenset({"van", "thi"})
_SEPARATOR_RE: Final = re.compile(r"\s*(?:\||•|·|;|,|\(|\s[-\u2013\u2014]\s|\t|\s{2,})\s*")
_LABEL_RE: Final = re.compile(
    r"^[\s\-*•·]*(?:"
    + "|".join(re.escape(item) for item in sorted(NAME_LABELS, key=len, reverse=True))
    + r")\s*[:\uff1a]\s*(?P<value>\S.*)$"
)
_HONORIFIC_RE: Final = re.compile(
    r"^[\s\-*•·\d.)]*(?:"
    + "|".join(re.escape(item) for item in HONORIFICS)
    + r")\.?\s+(?P<rest>\S.*)$"
)
_EXCLUDED_PHRASE_RES: Final = tuple(
    re.compile(rf"(?<![^\W_]){re.escape(phrase)}(?![^\W_])") for phrase in EXCLUDED_PHRASES
)
_EMAIL_LOCAL_RE: Final = re.compile(r"([A-Za-z0-9._%+\-]+)@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@dataclass(frozen=True, slots=True)
class NameAnchor:
    """A candidate name occurrence whose tokens are searched for elsewhere. Transient."""

    part_index: int
    start: int
    end: int
    tokens: tuple[str, ...]
    confidence: float
    detector_id: str
    signals: tuple[str, ...]

    def hit(self) -> Hit:
        return Hit(
            EntityType.CANDIDATE_NAME,
            self.start,
            self.end,
            self.confidence,
            self.detector_id,
            self.signals,
        )

    @property
    def folded_tokens(self) -> tuple[str, ...]:
        return tuple(fold(token) for token in self.tokens)


def is_name_token(token: str) -> bool:
    if len(token) == 2 and token[1] == "." and token[0].isalpha() and token[0].isupper():
        return True
    pieces = token.split("-")
    return all(_is_name_piece(piece) for piece in pieces)


def _is_name_piece(piece: str) -> bool:
    if len(piece) < 2 or not piece.isalpha():
        return False
    return piece.isupper() or (piece[0].isupper() and piece[1:].islower())


def is_excluded(tokens: tuple[str, ...]) -> bool:
    folded = tuple(fold(token).strip(".") for token in tokens)
    if any(token in EXCLUDED_TOKENS for token in folded):
        return True
    joined = " ".join(folded)
    if is_heading_text(joined):
        return True
    return any(pattern.search(joined) for pattern in _EXCLUDED_PHRASE_RES)


def is_name_shaped(tokens: tuple[str, ...], *, minimum: int = 2) -> bool:
    if not minimum <= len(tokens) <= 5:
        return False
    if not all(is_name_token(token) for token in tokens):
        return False
    if all(len(token) == 2 and token.endswith(".") for token in tokens):
        return False
    return not is_excluded(tokens)


def email_tokens(views: tuple[PartView, ...]) -> frozenset[str]:
    found: set[str] = set()
    for view in views:
        for match in _EMAIL_LOCAL_RE.finditer(view.text):
            for piece in re.split(r"[._%+\-\d]+", fold(match.group(1))):
                if len(piece) >= 2:
                    found.add(piece)
    return frozenset(found)


def label_names(view: PartView, index: int) -> tuple[list[NameAnchor], list[Hit]]:
    """Values of name labels. Inside a reference section they are referee names."""
    anchors: list[NameAnchor] = []
    references: list[Hit] = []
    for line in view.lines:
        match = _LABEL_RE.match(line.folded)
        if match is None:
            continue
        value_start = line.span(match.start("value"), match.start("value") + 1)[0]
        segment = _first_segment(view.text, value_start, line.end, cut_label=True)
        if segment is None:
            continue
        start, end, tokens = segment
        if any(char.isdigit() for char in view.text[start:end]):
            continue
        shaped = is_name_shaped(tokens, minimum=1) and len(tokens) >= 2
        if view.section_at(start) is SectionKind.REFERENCE:
            signals = ("reference_section", "label")
            confidence = LABELED if shaped else LABEL_SHAPE_MISMATCH
            references.append(
                Hit(
                    EntityType.REFERENCE_NAME,
                    start,
                    end,
                    confidence,
                    "reference_name.label",
                    signals,
                )
            )
            continue
        if shaped:
            anchors.append(NameAnchor(index, start, end, tokens, LABELED, "name.label", ("label",)))
        elif not is_excluded(tokens):
            anchors.append(
                NameAnchor(
                    index,
                    start,
                    end,
                    tokens,
                    LABEL_SHAPE_MISMATCH,
                    "name.label",
                    ("label", "shape_mismatch"),
                )
            )
    return anchors, references


def header_candidate(view: PartView, index: int, emails: frozenset[str]) -> NameAnchor | None:
    """Best name-shaped line near the top of a contact part, scored by explicit signals."""
    heights = _line_heights(view)
    tallest = max(heights.values(), default=0.0)
    typical = statistics.median(heights.values()) if len(heights) >= 2 else 0.0
    best: NameAnchor | None = None
    rank = 0
    for line_index, line in enumerate(view.lines[: view.first_heading]):
        if not view.text[line.start : line.end].strip():
            continue
        if rank >= _HEADER_LINES:
            break
        segment = _first_segment(view.text, line.start, line.end)
        current_rank = rank
        rank += 1
        if segment is None:
            continue
        start, end, tokens = segment
        if not is_name_shaped(tokens):
            continue
        score = _HEADER_BASE
        signals = ["top_of_page"]
        if current_rank == 0:
            score += 0.05
            signals.append("first_line")
        folded = tuple(fold(token) for token in tokens)
        if folded[0] in VN_SURNAMES:
            score += 0.10
            signals.append("vn_surname")
        height = heights.get(line_index, 0.0)
        if typical > 0 and height >= typical * _LARGE_FONT_RATIO and height >= tallest * 0.95:
            score += 0.20
            signals.append("largest_font")
        if _email_agrees(folded, emails):
            score += 0.15
            signals.append("email_match")
        anchor = NameAnchor(
            index,
            start,
            end,
            tokens,
            round(min(score, _HEADER_CAP), 2),
            "name.header",
            tuple(signals),
        )
        if best is None or anchor.confidence > best.confidence:
            best = anchor
    return best


def reference_line_names(view: PartView) -> list[Hit]:
    """Referee names at the start of lines inside a reference section."""
    hits: list[Hit] = []
    for line in view.lines:
        if view.section_at(line.start) is not SectionKind.REFERENCE:
            continue
        if _LABEL_RE.match(line.folded) is not None:
            continue
        honorific = _HONORIFIC_RE.match(line.folded)
        if honorific is not None:
            rest = line.span(honorific.start("rest"), honorific.start("rest") + 1)[0]
            segment = _first_segment(view.text, rest, line.end)
            if segment is None:
                continue
            start, end, tokens = segment
            if 1 <= len(tokens) <= 4 and is_name_shaped(tokens, minimum=1):
                hits.append(
                    Hit(
                        EntityType.REFERENCE_NAME,
                        start,
                        end,
                        HONORIFIC,
                        "reference_name.honorific",
                        ("reference_section", "honorific"),
                    )
                )
            continue
        segment = _first_segment(view.text, line.start, line.end)
        if segment is None:
            continue
        start, end, tokens = segment
        if is_name_shaped(tokens):
            hits.append(
                Hit(
                    EntityType.REFERENCE_NAME,
                    start,
                    end,
                    REFERENCE_LINE,
                    "reference_name.line",
                    ("reference_section", "line_start"),
                )
            )
    return hits


def repeat_hits(view: PartView, index: int, anchors: list[NameAnchor]) -> list[Hit]:
    """Exact, diacritic-free, case-folded, and reordered variants of each anchor."""
    folded, fmap, _ = fold_with_map(view.text)
    hits: list[Hit] = []
    for anchor in anchors:
        own = (anchor.start, anchor.end) if anchor.part_index == index else None
        for variant in _variants(anchor.folded_tokens):
            pattern = (
                r"(?<![^\W_])" + r"\s+".join(re.escape(tok) for tok in variant) + r"(?![^\W_])"
            )
            for match in re.finditer(pattern, folded):
                start, end = original_span(fmap, match.start(), match.end())
                if end <= start or (start, end) == own:
                    continue
                hits.append(
                    Hit(
                        EntityType.CANDIDATE_NAME,
                        start,
                        end,
                        anchor.confidence,
                        "name.repeat",
                        (*anchor.signals, "repeat"),
                    )
                )
    return hits


def _variants(tokens: tuple[str, ...]) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = [tokens]
    if len(tokens) >= 2:
        found.append((tokens[-1], *tokens[:-1]))
    if len(tokens) >= 3:
        found.append((tokens[0], tokens[-1]))
        found.append((tokens[-1], tokens[0]))
    return list(dict.fromkeys(found))


def _email_agrees(folded: tuple[str, ...], emails: frozenset[str]) -> bool:
    strong = [token for token in folded if token not in _WEAK_EMAIL_TOKENS]
    matched = sum(1 for token in strong if token in emails)
    return matched >= min(2, len(strong)) and matched > 0


def _first_segment(
    text: str, start: int, end: int, *, cut_label: bool = False
) -> tuple[int, int, tuple[str, ...]] | None:
    """Leading run of the line up to a separator.

    With ``cut_label`` a following inline ``label:`` ends the run; otherwise a
    segment containing a colon is a label, not a name, and is rejected.
    """
    while start < end and text[start] in " \t-*•·":
        start += 1
    chunk = text[start:end]
    separator = _SEPARATOR_RE.search(chunk)
    if separator is not None:
        chunk = chunk[: separator.start()]
    colon = chunk.find(":")
    if colon >= 0:
        if not cut_label:
            return None
        cut = chunk.rfind(" ", 0, colon)
        chunk = chunk[:cut] if cut > 0 else ""
    chunk = chunk.rstrip()
    if not chunk:
        return None
    return start, start + len(chunk), tuple(chunk.split())


def _line_heights(view: PartView) -> dict[int, float]:
    heights: dict[int, float] = {}
    spans = [span for span in view.part.spans if span.boxes]
    if not spans:
        return heights
    for index, line in enumerate(view.lines):
        tallest = 0.0
        for span in spans:
            if span.start < line.end and span.end > line.start:
                for box in span.boxes:
                    tallest = max(tallest, box.y1 - box.y0)
        if tallest > 0:
            heights[index] = tallest
    return heights
