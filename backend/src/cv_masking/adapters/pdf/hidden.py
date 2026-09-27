# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Hidden-content scan shared by the extractor and the redactor's output check.

Reports categories, counts, and pages only; never the hidden content itself.
"""

from collections import defaultdict
from typing import Final

import pymupdf

from cv_masking.domain.findings import BoundingBox
from cv_masking.domain.hidden import HiddenContentAlert, HiddenContentCategory

MIN_VISIBLE_PT: Final = 2.0
JS_MARKERS: Final = ("/JavaScript", "/JS", "/Launch", "/SubmitForm", "/ImportData")
SKIP_ANNOT: Final = frozenset({"Link", "Widget"})
OPEN_ERRORS: Final = (RuntimeError, ValueError, OSError)

type HiddenPages = dict[HiddenContentCategory, set[int]]
type HiddenCounts = dict[HiddenContentCategory, int]


def silence_mupdf() -> None:
    tools = getattr(pymupdf, "TOOLS", None)
    if tools is None:
        return
    display_errors = getattr(tools, "mupdf_display_errors", None)
    display_warnings = getattr(tools, "mupdf_display_warnings", None)
    if callable(display_errors):
        display_errors(False)
    if callable(display_warnings):
        display_warnings(False)


def scan_hidden(document: pymupdf.Document) -> tuple[HiddenContentAlert, ...]:
    pages: HiddenPages = defaultdict(set)
    counts: HiddenCounts = defaultdict(int)
    collect_document_hidden(document, pages, counts)
    for index in range(document.page_count):
        collect_page_hidden(document.load_page(index), index + 1, pages, counts)
    return alerts(pages, counts)


def invisible_boxes(page: pymupdf.Page) -> tuple[BoundingBox, ...]:
    """Boxes of text a reader cannot see: render mode 3, fully transparent, tiny, white,
    or outside the crop box. The text trace reports the render mode as ``type``."""
    cropbox = page.cropbox
    crop = (float(cropbox.x0), float(cropbox.y0), float(cropbox.x1), float(cropbox.y1))
    found: list[BoundingBox] = []
    for item in page.get_texttrace():
        bbox = item.get("bbox")
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        size = float(item.get("size") or 0)
        render_mode = int(item.get("type") or 0)
        opacity = item.get("opacity")
        if (
            render_mode == 3
            or (isinstance(opacity, int | float) and float(opacity) <= 0.0)
            or size < MIN_VISIBLE_PT
            or _is_white(item.get("color"))
            or _outside_crop(bbox, crop)
        ):
            found_box = box(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            if found_box is not None:
                found.append(found_box)
    return tuple(found)


def collect_document_hidden(
    document: pymupdf.Document, pages: HiddenPages, counts: HiddenCounts
) -> None:
    first = 1
    embedded = int(document.embfile_count())
    if _has_collection(document):
        embedded += 1
    if embedded:
        pages[HiddenContentCategory.EMBEDDED_FILES].add(first)
        counts[HiddenContentCategory.EMBEDDED_FILES] += embedded
    if bool(getattr(document, "is_form_pdf", False)):
        pages[HiddenContentCategory.FORMS].add(first)
        counts[HiddenContentCategory.FORMS] += 1
    js_hits = javascript_hits(document)
    if js_hits:
        pages[HiddenContentCategory.JAVASCRIPT].add(first)
        counts[HiddenContentCategory.JAVASCRIPT] += js_hits
    for info in (document.get_ocgs() or {}).values():
        if isinstance(info, dict) and not bool(info.get("on", True)):
            pages[HiddenContentCategory.OPTIONAL_CONTENT].add(first)
            counts[HiddenContentCategory.OPTIONAL_CONTENT] += 1


def collect_page_hidden(
    page: pymupdf.Page, number: int, pages: HiddenPages, counts: HiddenCounts
) -> None:
    for annot in page.annots() or []:
        kind = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
        if kind in SKIP_ANNOT:
            if kind == "Widget":
                pages[HiddenContentCategory.FORMS].add(number)
                counts[HiddenContentCategory.FORMS] += 1
            continue
        pages[HiddenContentCategory.ANNOTATIONS].add(number)
        counts[HiddenContentCategory.ANNOTATIONS] += 1
    if invisible_boxes(page):
        pages[HiddenContentCategory.INVISIBLE_TEXT].add(number)
        counts[HiddenContentCategory.INVISIBLE_TEXT] += 1


def javascript_hits(document: pymupdf.Document) -> int:
    hits = 0
    for xref in range(1, document.xref_length()):
        try:
            raw = document.xref_object(xref)
        except OPEN_ERRORS:
            continue
        if isinstance(raw, str) and any(marker in raw for marker in JS_MARKERS):
            hits += 1
    return hits


def alerts(pages: HiddenPages, counts: HiddenCounts) -> tuple[HiddenContentAlert, ...]:
    found_alerts: list[HiddenContentAlert] = []
    for category in HiddenContentCategory:
        found = pages.get(category)
        count = counts.get(category, 0)
        if not found or count < 1:
            continue
        found_alerts.append(HiddenContentAlert(category, count, tuple(sorted(found))))
    return tuple(found_alerts)


def box(x0: float, y0: float, x1: float, y1: float) -> BoundingBox | None:
    left, bottom, right, top = (round(value, 3) for value in (x0, y0, x1, y1))
    if left >= right or bottom >= top:
        return None
    return BoundingBox(left, bottom, right, top)


def overlaps_any(target: BoundingBox, others: tuple[BoundingBox, ...]) -> bool:
    return any(
        target.x0 < other.x1
        and target.x1 > other.x0
        and target.y0 < other.y1
        and target.y1 > other.y0
        for other in others
    )


def _has_collection(document: pymupdf.Document) -> bool:
    try:
        catalog = document.pdf_catalog()
        kind, _value = document.xref_get_key(catalog, "Collection")
    except OPEN_ERRORS:
        return False
    return kind not in {None, "null", ""}


def _outside_crop(
    bbox: list[object] | tuple[object, ...], crop: tuple[float, float, float, float]
) -> bool:
    numbers: list[float] = []
    for value in bbox[:4]:
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False
        numbers.append(float(value))
    if len(numbers) != 4:
        return False
    x0, y0, x1, y1 = numbers
    return x1 < crop[0] or x0 > crop[2] or y1 < crop[1] or y0 > crop[3]


def _is_white(color: object) -> bool:
    if isinstance(color, bool):
        return False
    if isinstance(color, int) and color == 0xFFFFFF:
        return True
    if isinstance(color, int | float):
        return float(color) >= 0.98
    if isinstance(color, list | tuple) and color:
        return all(
            isinstance(channel, int | float)
            and not isinstance(channel, bool)
            and float(channel) >= 0.98
            for channel in color
        )
    return False
