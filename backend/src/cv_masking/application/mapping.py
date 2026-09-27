"""Map PDF character ranges to source word boxes and group overlaps into regions.

Works on offsets and geometry only; no text is kept or returned. Mapping errs
toward over-redaction: a partly covered word is redacted whole, and a word
drawn on top of another pulls both boxes in and flags the finding as ambiguous.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from cv_masking.domain.findings import (
    BoundingBox,
    DocxLocation,
    DocxRedactionRange,
    EntityFinding,
    PdfLocation,
    RedactionRegion,
)
from cv_masking.domain.policy import label_winner
from cv_masking.ports.extraction import TextPart

SAME_LINE_RATIO: Final = 0.5
"""Two boxes share a line when they overlap vertically by this share of the shorter one."""
TWIN_RATIO: Final = 0.5
"""A word drawn over another covers at least this share of the smaller box's area."""
MAX_WORD_GAP_RATIO: Final = 1.0
"""Consecutive words merge into one line box only across a gap up to this many line heights."""
_EPSILON: Final = 0.01


@dataclass(frozen=True, slots=True)
class SpanMapping:
    boxes: tuple[BoundingBox, ...]
    ambiguous: bool
    partial_words: int


def map_span(part: TextPart, start: int, end: int) -> SpanMapping | None:
    """Boxes covering ``[start, end)`` on one PDF page, or None when any visible character
    of the range has no source box (the caller fails the document)."""
    if not (0 <= start < end <= len(part.text)):
        return None
    chosen = [
        index
        for index, span in enumerate(part.spans)
        if span.boxes and span.start < end and span.end > start
    ]
    if not chosen or not _fully_covered(part, start, end, chosen):
        return None
    chosen_set = set(chosen)
    word_boxes = [box for index in chosen for box in part.spans[index].boxes]
    others = [
        box
        for index, span in enumerate(part.spans)
        if index not in chosen_set
        for box in span.boxes
    ]
    twins = [other for other in others if any(_is_twin(box, other) for box in word_boxes)]
    neighbours = [other for other in others if other not in twins]
    partial = sum(
        1 for index in chosen if part.spans[index].start < start or part.spans[index].end > end
    )
    lines = _merge_lines(word_boxes, neighbours)
    return SpanMapping(_without_contained([*lines, *twins]), bool(twins), partial)


def build_regions(findings: Sequence[EntityFinding]) -> tuple[RedactionRegion, ...]:
    """Merge PDF findings whose boxes overlap on a line; label with the winning type."""
    located = [
        (finding, finding.location)
        for finding in findings
        if isinstance(finding.location, PdfLocation)
    ]
    parent = list(range(len(located)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(located)):
        for right in range(left + 1, len(located)):
            first, second = located[left][1], located[right][1]
            if first.page_number != second.page_number:
                continue
            if any(_overlaps(a, b) for a in first.boxes for b in second.boxes):
                parent[root(right)] = root(left)
    groups: dict[int, list[int]] = {}
    for index in range(len(located)):
        groups.setdefault(root(index), []).append(index)
    regions: list[RedactionRegion] = []
    for members in groups.values():
        page = located[members[0]][1].page_number
        boxes = _merge_overlapping([box for i in members for box in located[i][1].boxes])
        regions.append(
            RedactionRegion(
                page_number=page,
                boxes=boxes,
                entity_type=label_winner(located[i][0].entity_type for i in members),
                finding_ids=tuple(located[i][0].finding_id for i in members),
            )
        )
    return tuple(sorted(regions, key=lambda r: (r.page_number, r.boxes[0].y0, r.boxes[0].x0)))


def build_docx_ranges(findings: Sequence[EntityFinding]) -> tuple[DocxRedactionRange, ...]:
    """Merge DOCX findings whose ranges overlap in one part; label with the winning type."""
    located = sorted(
        (
            (finding, finding.location)
            for finding in findings
            if isinstance(finding.location, DocxLocation)
        ),
        key=lambda item: (item[1].part_name, item[1].start, item[1].end),
    )
    groups: list[list[tuple[EntityFinding, DocxLocation]]] = []
    for item in located:
        last = groups[-1] if groups else None
        if (
            last is not None
            and last[0][1].part_name == item[1].part_name
            and item[1].start < max(member[1].end for member in last)
        ):
            last.append(item)
        else:
            groups.append([item])
    return tuple(
        DocxRedactionRange(
            part_name=group[0][1].part_name,
            start=group[0][1].start,
            end=max(member[1].end for member in group),
            entity_type=label_winner(member[0].entity_type for member in group),
            finding_ids=tuple(member[0].finding_id for member in group),
        )
        for group in groups
    )


def _fully_covered(part: TextPart, start: int, end: int, chosen: list[int]) -> bool:
    covered = [False] * (end - start)
    for index in chosen:
        span = part.spans[index]
        for offset in range(max(span.start, start), min(span.end, end)):
            covered[offset - start] = True
    return all(covered[i] or part.text[start + i].isspace() for i in range(end - start))


def _merge_lines(word_boxes: list[BoundingBox], neighbours: list[BoundingBox]) -> list[BoundingBox]:
    merged: list[BoundingBox] = []
    for box in word_boxes:
        if merged:
            candidate = _extend(merged[-1], box, neighbours)
            if candidate is not None:
                merged[-1] = candidate
                continue
        merged.append(box)
    return merged


def _extend(
    line: BoundingBox, box: BoundingBox, neighbours: list[BoundingBox]
) -> BoundingBox | None:
    if not _same_line(line, box) or box.x0 < line.x0 - _EPSILON:
        return None
    height = min(line.y1 - line.y0, box.y1 - box.y0)
    if box.x0 - line.x1 > height * MAX_WORD_GAP_RATIO:
        return None
    candidate = _union(line, box)
    if any(_overlaps(candidate, other) for other in neighbours):
        return None
    return candidate


def _merge_overlapping(boxes: list[BoundingBox]) -> tuple[BoundingBox, ...]:
    pending = list(dict.fromkeys(boxes))
    changed = True
    while changed:
        changed = False
        for left in range(len(pending)):
            for right in range(left + 1, len(pending)):
                if _overlaps(pending[left], pending[right]):
                    pending[left] = _union(pending[left], pending.pop(right))
                    changed = True
                    break
            if changed:
                break
    return tuple(sorted(pending, key=lambda box: (box.y0, box.x0)))


def _without_contained(boxes: list[BoundingBox]) -> tuple[BoundingBox, ...]:
    unique = list(dict.fromkeys(boxes))
    kept = [
        box
        for box in unique
        if not any(other is not box and _contains(other, box) for other in unique)
    ]
    return tuple(kept)


def _same_line(a: BoundingBox, b: BoundingBox) -> bool:
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return overlap >= SAME_LINE_RATIO * min(a.y1 - a.y0, b.y1 - b.y0)


def _overlaps(a: BoundingBox, b: BoundingBox) -> bool:
    """Overlap on the same line; boxes on neighbouring lines that touch do not count."""
    return _same_line(a, b) and min(a.x1, b.x1) - max(a.x0, b.x0) > _EPSILON


def _is_twin(a: BoundingBox, b: BoundingBox) -> bool:
    width = min(a.x1, b.x1) - max(a.x0, b.x0)
    height = min(a.y1, b.y1) - max(a.y0, b.y0)
    if width <= 0 or height <= 0:
        return False
    smaller = min(_area(a), _area(b))
    return width * height >= TWIN_RATIO * smaller


def _contains(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.x0 <= inner.x0
        and outer.y0 <= inner.y0
        and inner.x1 <= outer.x1
        and inner.y1 <= outer.y1
    )


def _union(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    return BoundingBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _area(box: BoundingBox) -> float:
    return (box.x1 - box.x0) * (box.y1 - box.y0)
