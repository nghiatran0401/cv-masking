# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Permanent PDF redaction with PyMuPDF redaction annotations and apply_redactions.

Text under every region is removed from the content stream; the black box and
label are drawn by ``apply_redactions`` itself, never as a separate overlay.
The input bytes are never modified; the output is a fresh, fully rewritten
PDF that is re-opened and checked before it is returned.
"""

import math
import re
from collections import defaultdict
from typing import Final

import pymupdf

from cv_masking.adapters.pdf.content import ContentError, decode_name, strip_hidden
from cv_masking.adapters.pdf.extractor import MAX_XREFS
from cv_masking.adapters.pdf.hidden import (
    JS_MARKERS,
    OPEN_ERRORS,
    SKIP_ANNOT,
    invisible_boxes,
    scan_hidden,
    silence_mupdf,
)
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.findings import BoundingBox, RedactionRegion
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES
from cv_masking.domain.policy import REPLACEMENT_LABELS
from cv_masking.ports.redaction import RedactionResult

MIN_LABEL_PT: Final = 6.0
"""masking-policy.md §5: a label is drawn only if it fits at 6 pt or more."""
_MAX_LABEL_PT: Final = 10.0
_LABEL_FONT: Final = "helv"
_LABEL_LINE_HEIGHT: Final = 1.25
_LABEL_PADDING: Final = 1.0
_SAME_LINE_RATIO: Final = 0.5
_TRIM_GAP: Final = 0.25
_RENDER_SCALE: Final = 0.5
_MAX_FORM_DEPTH: Final = 8
_BLACK: Final = (0.0, 0.0, 0.0)
_LABEL_GREY: Final = (0.9, 0.9, 0.9)
"""Near-white: pure white text is classed as hidden content by the scan the output must pass."""
_LABELS: Final = frozenset(REPLACEMENT_LABELS.values())
_ACTION_TYPES: Final = frozenset({"/JavaScript", "/Launch", "/SubmitForm", "/ImportData"})
_STALE_PAGE_MODES: Final = frozenset({"/UseOutlines", "/UseThumbs", "/UseOC", "/UseAttachments"})
_CATALOG_STRIPPED: Final = ("Outlines", "PageLabels", "Metadata", "StructTreeRoot", "MarkInfo")
_PAGE_STRIPPED: Final = ("Thumb", "StructParents")
_OBJECT_STRIPPED: Final = ("Metadata", "PieceInfo", "StructParent")
"""Tagged-structure alt text and application private data can hold text not on the page."""
_DROPPED_KEYS: Final = (
    "AA",
    "AcroForm",
    "Collection",
    "EmbeddedFiles",
    "JavaScript",
    "MarkInfo",
    "Metadata",
    "OCProperties",
    "OpenAction",
    "Outlines",
    "PageLabels",
    "PageMode",
    "PieceInfo",
    "StructParent",
    "StructParents",
    "StructTreeRoot",
    "Thumb",
)
_NULL_ENTRY_RE: Final = re.compile(rf"/(?:{'|'.join(_DROPPED_KEYS)})\s+null\b")
"""``xref_set_key(..., "null")`` leaves ``/Key null`` behind; the scans are textual."""
_REF_RE: Final = re.compile(r"(\d+)\s+\d+\s+R")
_NAMED_REF_RE: Final = re.compile(r"/([^\s/<>\[\]()]+)\s*(\d+)\s+\d+\s+R")
_ERRORS: Final = (*OPEN_ERRORS, pymupdf.mupdf.FzErrorBase)


class _RedactionError(Exception):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class PyMuPDFRedactor:
    """Redacts regions, strips always-removed metadata, and removes approved hidden content."""

    def redact(
        self, data: bytes, regions: tuple[RedactionRegion, ...], *, remove_hidden: bool
    ) -> RedactionResult:
        if not data:
            return RedactionResult(failure=ErrorCode.REDACT_FAILED)
        silence_mupdf()
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except _ERRORS:
            return RedactionResult(failure=ErrorCode.REDACT_FAILED)
        try:
            return _redact(document, regions, remove_hidden=remove_hidden)
        except _RedactionError as failure:
            return RedactionResult(failure=failure.code)
        except _ERRORS:
            return RedactionResult(failure=ErrorCode.REDACT_FAILED)
        finally:
            document.close()


def _redact(
    document: pymupdf.Document, regions: tuple[RedactionRegion, ...], *, remove_hidden: bool
) -> RedactionResult:
    pages = document.page_count
    if (
        bool(getattr(document, "is_encrypted", False))
        or bool(getattr(document, "needs_pass", False))
        or not 1 <= pages <= HARD_MAX_PDF_PAGES
        or document.xref_length() > MAX_XREFS
        or any(region.page_number > pages for region in regions)
    ):
        raise _RedactionError(ErrorCode.REDACT_FAILED)
    found = {alert.category for alert in scan_hidden(document)}
    if found and not remove_hidden:
        raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED)
    hidden_boxes = _sanitize(document, found)
    by_page: dict[int, list[RedactionRegion]] = defaultdict(list)
    for region in regions:
        by_page[region.page_number].append(region)
    labelled = 0
    for index in range(pages):
        page = document.load_page(index)
        labelled += _mark_page(page, by_page.get(index + 1, []), hidden_boxes.get(index, ()))
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
    _drop_null_entries(document)
    output = document.tobytes(garbage=4, deflate=True)
    _check_output(output, pages, regions)
    return RedactionResult(
        output=output, labelled_regions=labelled, solid_regions=len(regions) - labelled
    )


def _sanitize(
    document: pymupdf.Document, found: set[HiddenContentCategory]
) -> dict[int, tuple[pymupdf.Rect, ...]]:
    """Remove approved hidden content and always-stripped components.

    Returns the invisible-text boxes per page index; they are removed by the
    same ``apply_redactions`` call as the regions.
    """
    try:
        if HiddenContentCategory.OPTIONAL_CONTENT in found:
            _remove_optional_content(document)
        if HiddenContentCategory.ANNOTATIONS in found:
            _remove_annotations(document)
        if HiddenContentCategory.FORMS in found:
            _remove_forms(document)
        if HiddenContentCategory.EMBEDDED_FILES in found:
            _remove_embedded_files(document)
        if HiddenContentCategory.JAVASCRIPT in found:
            _remove_javascript(document)
        hidden_boxes: dict[int, tuple[pymupdf.Rect, ...]] = {}
        if HiddenContentCategory.INVISIBLE_TEXT in found:
            for index in range(document.page_count):
                boxes = invisible_boxes(document.load_page(index))
                if boxes:
                    hidden_boxes[index] = tuple(_rect(item) for item in boxes)
        _strip_always(document)
    except (ContentError, *_ERRORS) as error:
        raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED) from error
    return hidden_boxes


def _mark_page(
    page: pymupdf.Page, regions: list[RedactionRegion], hidden: tuple[pymupdf.Rect, ...]
) -> int:
    """Add redaction annotations; return how many regions got a label."""
    for rect in hidden:
        # PyMuPDF documents fill=False as "no fill"; its stub only admits colours.
        page.add_redact_annot(rect, fill=False, cross_out=False)  # type: ignore[arg-type]
    if not regions:
        return 0
    words = tuple(pymupdf.Rect(item[:4]) for item in page.get_text("words"))
    labelled = 0
    for region in regions:
        rects = [_trim(_rect(item), words) for item in region.boxes]
        label = region.replacement_label
        sizes = [_label_size(label, rect) for rect in rects]
        best = max(range(len(rects)), key=lambda index: sizes[index] or 0.0)
        chosen = best if sizes[best] is not None else None
        labelled += int(chosen is not None)
        for index, rect in enumerate(rects):
            size = sizes[index]
            if index == chosen and size is not None:
                page.add_redact_annot(
                    rect,
                    text=label,
                    fontname=_LABEL_FONT,
                    fontsize=size,
                    align=pymupdf.TEXT_ALIGN_CENTER,
                    fill=_BLACK,
                    text_color=_LABEL_GREY,
                    cross_out=False,
                )
            else:
                page.add_redact_annot(rect, fill=_BLACK, cross_out=False)
    return labelled


def _trim(box: pymupdf.Rect, words: tuple[pymupdf.Rect, ...]) -> pymupdf.Rect:
    """Clip the box vertically so it no longer touches words on the lines above and below.

    Word boxes on tightly spaced lines overlap by a few points, and
    ``apply_redactions`` removes every glyph the rectangle touches. If the
    neighbours leave no band, the untrimmed box is used: over-redaction, never less.
    """
    top, bottom = box.y0, box.y1
    for word in words:
        if word.x1 <= box.x0 or word.x0 >= box.x1 or word.y1 <= box.y0 or word.y0 >= box.y1:
            continue
        overlap = min(word.y1, box.y1) - max(word.y0, box.y0)
        if overlap >= _SAME_LINE_RATIO * min(word.height, box.height):
            continue
        if word.y0 + word.y1 < box.y0 + box.y1:
            top = max(top, word.y1 + _TRIM_GAP)
        else:
            bottom = min(bottom, word.y0 - _TRIM_GAP)
    if bottom <= top:
        return box
    return pymupdf.Rect(box.x0, top, box.x1, bottom)


def _label_size(label: str, rect: pymupdf.Rect) -> float | None:
    unit_width = pymupdf.get_text_length(label, fontname=_LABEL_FONT, fontsize=1)
    width = rect.width - 2 * _LABEL_PADDING
    if unit_width <= 0 or width <= 0:
        return None
    size = min(_MAX_LABEL_PT, width / unit_width, rect.height / _LABEL_LINE_HEIGHT)
    size = math.floor(size * 2) / 2
    return size if size >= MIN_LABEL_PT else None


def _rect(item: BoundingBox) -> pymupdf.Rect:
    return pymupdf.Rect(item.x0, item.y0, item.x1, item.y1)


def _strip_always(document: pymupdf.Document) -> None:
    """masking-policy.md §6: metadata, XMP, links, outlines, thumbnails, page labels, tags."""
    document.set_metadata({})
    document.del_xml_metadata()
    document.set_toc([])
    catalog = document.pdf_catalog()
    for key in _CATALOG_STRIPPED:
        document.xref_set_key(catalog, key, "null")
    if document.xref_get_key(catalog, "PageMode")[1] in _STALE_PAGE_MODES:
        document.xref_set_key(catalog, "PageMode", "null")
    for xref in range(1, document.xref_length()):
        for key in _OBJECT_STRIPPED:
            if document.xref_get_key(xref, key)[0] != "null":
                document.xref_set_key(xref, key, "null")
    for index in range(document.page_count):
        page = document.load_page(index)
        for link in page.get_links():
            page.delete_link(link)
        for key in _PAGE_STRIPPED:
            document.xref_set_key(page.xref, key, "null")


def _drop_null_entries(document: pymupdf.Document) -> None:
    for xref in range(1, document.xref_length()):
        if document.xref_is_stream(xref):
            continue
        raw = document.xref_object(xref)
        cleaned = _NULL_ENTRY_RE.sub("", raw)
        if cleaned != raw:
            document.update_object(xref, cleaned)


def _remove_annotations(document: pymupdf.Document) -> None:
    for index in range(document.page_count):
        page = document.load_page(index)
        doomed = [
            annot.xref
            for annot in page.annots() or []
            if not (isinstance(annot.type, tuple) and annot.type[1] in SKIP_ANNOT)
        ]
        for xref in doomed:
            page.delete_annot(page.load_annot(xref))


def _remove_forms(document: pymupdf.Document) -> None:
    for index in range(document.page_count):
        page = document.load_page(index)
        for widget in list(page.widgets()):
            page.delete_widget(widget)
    document.xref_set_key(document.pdf_catalog(), "AcroForm", "null")


def _remove_embedded_files(document: pymupdf.Document) -> None:
    for name in document.embfile_names():
        document.embfile_del(name)
    catalog = document.pdf_catalog()
    document.xref_set_key(catalog, "Collection", "null")
    if document.xref_get_key(catalog, "Names")[0] != "null":
        document.xref_set_key(catalog, "Names/EmbeddedFiles", "null")


def _remove_javascript(document: pymupdf.Document) -> None:
    catalog = document.pdf_catalog()
    for key in ("OpenAction", "AA"):
        document.xref_set_key(catalog, key, "null")
    if document.xref_get_key(catalog, "Names")[0] != "null":
        document.xref_set_key(catalog, "Names/JavaScript", "null")
    for index in range(document.page_count):
        document.xref_set_key(document.load_page(index).xref, "AA", "null")
    for xref in range(1, document.xref_length()):
        raw = document.xref_object(xref)
        if not any(marker in raw for marker in JS_MARKERS):
            continue
        if (
            document.xref_get_key(xref, "S")[1] in _ACTION_TYPES
            or document.xref_get_key(xref, "JS")[0] != "null"
        ):
            document.update_object(xref, "<<>>")


def _remove_optional_content(document: pymupdf.Document) -> None:
    """Drop painting in hidden layers, then the layer definitions themselves.

    Rendering must be identical before and after: that proves no visible
    content was lost and no hidden content became visible.
    """
    hidden = {
        int(xref)
        for xref, info in (document.get_ocgs() or {}).items()
        if isinstance(info, dict) and not bool(info.get("on", True))
    }
    before = [_render(document.load_page(index)) for index in range(document.page_count)]
    filtered: set[int] = set()
    blank: set[int] = set()
    for index in range(document.page_count):
        page = document.load_page(index)
        owner = _resources_owner(document, page.xref)
        data = page.read_contents()
        cleaned, removed = _strip(document, data, owner, hidden, filtered, blank, depth=0)
        if removed:
            xref = document.get_new_xref()
            document.update_object(xref, "<<>>")
            document.update_stream(xref, cleaned)
            page.set_contents(xref)
    for xref in blank:
        document.update_object(xref, "<< /Type /XObject /Subtype /Form /BBox [0 0 0 0] >>")
        document.update_stream(xref, b"")
    document.xref_set_key(document.pdf_catalog(), "OCProperties", "null")
    after = [_render(document.load_page(index)) for index in range(document.page_count)]
    if before != after:
        raise ContentError("hidden-layer removal changed the rendered page")


def _strip(
    document: pymupdf.Document,
    data: bytes,
    owner: int | None,
    hidden: set[int],
    filtered: set[int],
    blank: set[int],
    *,
    depth: int,
) -> tuple[bytes, int]:
    """Filter one content stream and, recursively, the form XObjects it uses.

    XObjects whose own ``/OC`` is hidden are collected in ``blank``; the caller
    empties them so their bytes do not survive in the output.
    """
    if depth > _MAX_FORM_DEPTH:
        raise ContentError("form XObjects nested too deeply")
    properties = _named_refs(document, owner, "Resources/Properties")
    xobjects = _named_refs(document, owner, "Resources/XObject")
    hidden_xobjects = {
        name for name, xref in xobjects.items() if _xobject_hidden(document, xref, hidden)
    }
    blank.update(xobjects[name] for name in hidden_xobjects)
    for name, xref in xobjects.items():
        if (
            name in hidden_xobjects
            or xref in filtered
            or document.xref_get_key(xref, "Subtype")[1] != "/Form"
        ):
            continue
        filtered.add(xref)
        form_owner = xref if document.xref_get_key(xref, "Resources")[0] != "null" else owner
        cleaned, removed = _strip(
            document,
            document.xref_stream(xref),
            form_owner,
            hidden,
            filtered,
            blank,
            depth=depth + 1,
        )
        if removed:
            document.update_stream(xref, cleaned)

    def hidden_property(name: bytes) -> bool:
        if name not in properties:
            raise ContentError("unknown optional-content name")
        return _oc_hidden(document, properties[name], hidden)

    return strip_hidden(
        data, hidden_property=hidden_property, hidden_xobject=hidden_xobjects.__contains__
    )


def _xobject_hidden(document: pymupdf.Document, xref: int, hidden: set[int]) -> bool:
    kind, value = document.xref_get_key(xref, "OC")
    if kind == "null":
        return False
    if kind != "xref":
        raise ContentError("inline optional-content dictionary")
    return _oc_hidden(document, _first_ref(value), hidden)


def _oc_hidden(document: pymupdf.Document, xref: int, hidden: set[int]) -> bool:
    kind = document.xref_get_key(xref, "Type")[1]
    if kind == "/OCG":
        return xref in hidden
    if kind != "/OCMD" or document.xref_get_key(xref, "VE")[0] != "null":
        raise ContentError("unsupported optional-content membership")
    groups_kind, groups = document.xref_get_key(xref, "OCGs")
    refs = [int(ref) for ref in _REF_RE.findall(groups)] if groups_kind != "null" else []
    if not refs:
        return False
    on = [ref not in hidden for ref in refs]
    policy = document.xref_get_key(xref, "P")[1]
    visible = {
        "/AllOn": all(on),
        "/AnyOff": not all(on),
        "/AllOff": not any(on),
    }.get(policy, any(on))
    return not visible


def _resources_owner(document: pymupdf.Document, xref: int) -> int | None:
    """The page, or the nearest ancestor, that holds the inherited Resources."""
    owner = xref
    for _ in range(32):
        if document.xref_get_key(owner, "Resources")[0] != "null":
            return owner
        kind, value = document.xref_get_key(owner, "Parent")
        if kind != "xref":
            return None
        owner = _first_ref(value)
    return None


def _named_refs(document: pymupdf.Document, owner: int | None, key: str) -> dict[bytes, int]:
    if owner is None:
        return {}
    kind, value = document.xref_get_key(owner, key)
    if kind == "xref":
        value = document.xref_object(_first_ref(value))
    elif kind != "dict":
        return {}
    return {
        decode_name(match.group(1).encode("latin-1")): int(match.group(2))
        for match in _NAMED_REF_RE.finditer(value)
    }


def _first_ref(value: str) -> int:
    match = _REF_RE.search(value)
    if match is None:
        raise ContentError("expected an indirect reference")
    return int(match.group(1))


def _render(page: pymupdf.Page) -> bytes:
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(_RENDER_SCALE, _RENDER_SCALE), alpha=False, annots=False
    )
    return bytes(pixmap.samples)


def _check_output(output: bytes, pages: int, regions: tuple[RedactionRegion, ...]) -> None:
    """Re-open the output: same page count, nothing hidden or stripped left, regions empty."""
    try:
        document = pymupdf.open(stream=output, filetype="pdf")
    except _ERRORS as error:
        raise _RedactionError(ErrorCode.REDACT_FAILED) from error
    try:
        if document.page_count != pages or _has_redact_annots(document):
            raise _RedactionError(ErrorCode.REDACT_FAILED)
        for region in regions:
            if _region_has_text(document.load_page(region.page_number - 1), region):
                raise _RedactionError(ErrorCode.REDACT_FAILED)
        if scan_hidden(document) or _has_stripped_residue(document):
            raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED)
    finally:
        document.close()


def _has_stripped_residue(document: pymupdf.Document) -> bool:
    metadata = document.metadata or {}
    if any(value for key, value in metadata.items() if key not in {"format", "encryption"}):
        return True
    if document.get_xml_metadata() or document.get_toc():
        return True
    catalog = document.pdf_catalog()
    if any(document.xref_get_key(catalog, key)[0] != "null" for key in _CATALOG_STRIPPED):
        return True
    for xref in range(1, document.xref_length()):
        if any(document.xref_get_key(xref, key)[0] != "null" for key in _OBJECT_STRIPPED):
            return True
    for index in range(document.page_count):
        page = document.load_page(index)
        if page.get_links() or any(
            document.xref_get_key(page.xref, key)[0] != "null" for key in _PAGE_STRIPPED
        ):
            return True
    return False


def _has_redact_annots(document: pymupdf.Document) -> bool:
    return any(
        annot.type[0] == pymupdf.PDF_ANNOT_REDACT
        for index in range(document.page_count)
        for annot in document.load_page(index).annots() or []
    )


def _region_has_text(page: pymupdf.Page, region: RedactionRegion) -> bool:
    boxes = tuple(_rect(item) for item in region.boxes)
    for item in page.get_text("words"):
        if item[4] in _LABELS:
            continue
        word = pymupdf.Rect(item[:4])
        centre = pymupdf.Point((word.x0 + word.x1) / 2, (word.y0 + word.y1) / 2)
        if any(rect.contains(centre) for rect in boxes):
            return True
    return False
