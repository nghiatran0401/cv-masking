"""Lines and section headings of one extracted part. Offsets index the part text."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from cv_masking.adapters.detection.normalize import fold_with_map, original_span
from cv_masking.ports.extraction import TextPart


class SectionKind(StrEnum):
    REFERENCE = "reference"
    FAMILY = "family"
    OTHER = "other"


REFERENCE_HEADINGS: Final = (
    "nguoi tham chieu",
    "nguoi tham khao",
    "nguoi gioi thieu",
    "thong tin tham chieu",
    "references",
    "referees",
    "reference",
)
FAMILY_HEADINGS: Final = (
    "thong tin gia dinh",
    "quan he gia dinh",
    "hoan canh gia dinh",
    "gia dinh",
    "family",
    "family background",
    "family information",
)
OTHER_HEADINGS: Final = (
    "kinh nghiem",
    "kinh nghiem lam viec",
    "qua trinh cong tac",
    "hoc van",
    "trinh do hoc van",
    "qua trinh hoc tap",
    "ky nang",
    "du an",
    "chung chi",
    "ngoai ngu",
    "hoat dong",
    "giai thuong",
    "so thich",
    "muc tieu",
    "muc tieu nghe nghiep",
    "thong tin ca nhan",
    "thong tin lien he",
    "experience",
    "work experience",
    "work history",
    "employment",
    "education",
    "skills",
    "projects",
    "certifications",
    "certificates",
    "languages",
    "activities",
    "awards",
    "interests",
    "hobbies",
    "objective",
    "career objective",
    "summary",
    "profile",
    "personal information",
    "personal details",
    "contact",
    "contact information",
)
_BULLET: Final = r"[\s\-*•·\d.)]*"


def _alternation(headings: tuple[str, ...]) -> str:
    return "|".join(re.escape(item) for item in sorted(headings, key=len, reverse=True))


_ANY: Final = _alternation(REFERENCE_HEADINGS + FAMILY_HEADINGS + OTHER_HEADINGS)
_BILINGUAL_TAIL: Final = rf"(?:\s*[/|]\s*(?:{_ANY}))*"


def _heading_re(headings: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(rf"^{_BULLET}(?:{_alternation(headings)}){_BILINGUAL_TAIL}\s*[:\uff1a]?\s*$")


def _inline_re(headings: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        rf"^{_BULLET}(?:{_alternation(headings)}){_BILINGUAL_TAIL}"
        rf"\s*[:\uff1a]\s*(?P<rest>\S.*)$"
    )


_PURE: Final = (
    (SectionKind.REFERENCE, _heading_re(REFERENCE_HEADINGS)),
    (SectionKind.FAMILY, _heading_re(FAMILY_HEADINGS)),
    (SectionKind.OTHER, _heading_re(OTHER_HEADINGS)),
)
_INLINE: Final = (
    (SectionKind.REFERENCE, _inline_re(REFERENCE_HEADINGS)),
    (SectionKind.FAMILY, _inline_re(FAMILY_HEADINGS)),
)


@dataclass(frozen=True, slots=True)
class Line:
    start: int
    end: int
    folded: str
    fmap: tuple[int, ...]

    def span(self, folded_start: int, folded_end: int) -> tuple[int, int]:
        start, end = original_span(self.fmap, folded_start, folded_end)
        return self.start + start, self.start + end


@dataclass(frozen=True, slots=True)
class Section:
    kind: SectionKind
    heading_line: int
    content_start: int
    content_end: int


@dataclass(frozen=True, slots=True)
class PartView:
    part: TextPart
    lines: tuple[Line, ...]
    headings: frozenset[int]
    sections: tuple[Section, ...]

    @property
    def text(self) -> str:
        return self.part.text

    @property
    def first_heading(self) -> int:
        return min(self.headings, default=len(self.lines))

    def section_at(self, offset: int) -> SectionKind | None:
        for section in self.sections:
            if section.content_start <= offset < section.content_end:
                return section.kind
        return None

    def ranges(self, kind: SectionKind) -> tuple[tuple[int, int], ...]:
        return tuple(
            (section.content_start, section.content_end)
            for section in self.sections
            if section.kind is kind
        )

    @property
    def is_contact_part(self) -> bool:
        name = self.part.part_name or ""
        return (
            self.part.page_number == 1
            or name == "word/document.xml"
            or name.startswith("word/header")
        )


def build_view(part: TextPart) -> PartView:
    lines = _split_lines(part.text)
    headings: set[int] = set()
    sections: list[Section] = []
    open_kind: SectionKind | None = None
    open_line = 0
    open_start = 0
    for index, line in enumerate(lines):
        found = _heading_of(line)
        if found is None:
            continue
        headings.add(index)
        if open_kind is not None:
            sections.append(Section(open_kind, open_line, open_start, line.start))
        open_kind, content_start = found
        open_line = index
        open_start = content_start if content_start is not None else _next_line_start(part, line)
    if open_kind is not None:
        sections.append(Section(open_kind, open_line, open_start, len(part.text)))
    return PartView(part, lines, frozenset(headings), tuple(sections))


def is_heading_text(folded: str) -> bool:
    return any(pattern.match(folded) for _, pattern in _PURE)


def _heading_of(line: Line) -> tuple[SectionKind, int | None] | None:
    for kind, pattern in _PURE:
        if pattern.match(line.folded):
            return kind, None
    for kind, pattern in _INLINE:
        match = pattern.match(line.folded)
        if match is not None:
            rest = match.start("rest")
            return kind, line.span(rest, rest + 1)[0]
    return None


def _split_lines(text: str) -> tuple[Line, ...]:
    lines: list[Line] = []
    offset = 0
    for raw in text.split("\n"):
        folded, fmap, _ = fold_with_map(raw)
        lines.append(Line(offset, offset + len(raw), folded, tuple(fmap)))
        offset += len(raw) + 1
    return tuple(lines)


def _next_line_start(part: TextPart, line: Line) -> int:
    return min(line.end + 1, len(part.text))
