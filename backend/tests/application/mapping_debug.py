"""Debug view of Stage 9 mapping for synthetic fixtures only.

It shows the extracted words under each redaction box with coordinates. It lives
in the test tree on purpose: runtime code must never render document text.
"""

from dataclasses import dataclass

from cv_masking.domain.findings import BoundingBox, RedactionRegion
from cv_masking.ports.extraction import ExtractedDocument


@dataclass(frozen=True, slots=True)
class DebugRow:
    entity_type: str
    page_number: int
    words: tuple[str, ...]
    box: tuple[float, float, float, float]


def words_under(document: ExtractedDocument, page_number: int, box: BoundingBox) -> list[str]:
    """Words whose box centre lies inside ``box``: what a redaction there would remove."""
    for part in document.parts:
        if part.page_number != page_number:
            continue
        found: list[str] = []
        for span in part.spans:
            for word_box in span.boxes:
                cx = (word_box.x0 + word_box.x1) / 2
                cy = (word_box.y0 + word_box.y1) / 2
                if box.x0 <= cx <= box.x1 and box.y0 <= cy <= box.y1:
                    found.append(part.text[span.start : span.end])
                    break
        return found
    return []


def debug_rows(document: ExtractedDocument, regions: tuple[RedactionRegion, ...]) -> list[DebugRow]:
    return [
        DebugRow(
            region.entity_type.value,
            region.page_number,
            tuple(words_under(document, region.page_number, box)),
            (round(box.x0, 1), round(box.y0, 1), round(box.x1, 1), round(box.y1, 1)),
        )
        for region in regions
        for box in region.boxes
    ]


def render(rows: list[DebugRow]) -> str:
    return "\n".join(
        f"p{row.page_number} {row.entity_type:<16} "
        f"[{row.box[0]:7.1f} {row.box[1]:7.1f} {row.box[2]:7.1f} {row.box[3]:7.1f}] "
        f"{' '.join(row.words)}"
        for row in rows
    )
