"""Independently verify a stored output against its stored source.

Nothing from the redactor is used: the output is read back from storage and
opened by a format inspector with a fresh parser handle. Checks, per
masking-policy.md §1.7:

- the inspector's structural checks (opens, renders, page count, metadata,
  attachments, links, hidden content);
- every distinctive source value (names, contacts, identifiers, full dates of
  birth, numbered addresses) is searched for in the output's normalized text
  and in its raw objects;
- no output word sits inside a redacted PDF finding box, unless it is a label;
- each DOCX part's text equals the source text with every redacted range
  replaced by its label (whitespace ignored: emptied paragraphs change breaks);
- the deterministic Stage 7 detectors, rerun on the output, find nothing the
  policy redacts.

Source values are read from the in-memory source extraction only for the
search. They are never stored, logged, or returned. The job transition
(``record_verification``) belongs to the Stage 12 worker.
"""

import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Final

from cv_masking.application.detection import DetectionOutcome
from cv_masking.application.mapping import build_docx_ranges
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import BoundingBox, PdfLocation
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import (
    DISCARD_THRESHOLD,
    REDACT_THRESHOLD,
    REPLACEMENT_LABELS,
    EntityType,
    MaskingPolicy,
)
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.clock import Clock
from cv_masking.ports.detection import DocumentDetector
from cv_masking.ports.extraction import ExtractedDocument, TextPart
from cv_masking.ports.storage import InputStore, OutputStore, StorageError, StoredObject
from cv_masking.ports.verification import InspectionError, OutputInspector

logger = logging.getLogger("cv_masking.verification")

VERIFIER_ID: Final = "cv_masking.verifier"
VERIFIER_VERSION: Final = "1.0.0"
MIN_SEARCHED_CHARS: Final = 6
"""Shorter values (``Nam``, ``1990``) occur in unrelated kept text; the position
check and the detector rerun cover them instead."""
_NAME_TYPES: Final = frozenset({EntityType.CANDIDATE_NAME, EntityType.REFERENCE_NAME})
_SHAPE_TYPES: Final = frozenset(
    {
        EntityType.EMAIL,
        EntityType.PHONE,
        EntityType.NATIONAL_ID,
        EntityType.PASSPORT,
        EntityType.PERSONAL_URL,
    }
)
_NUMBERED_TYPES: Final = frozenset({EntityType.DATE_OF_BIRTH, EntityType.POSTAL_ADDRESS})
_LABELS: Final = tuple(sorted(set(REPLACEMENT_LABELS.values()), key=len, reverse=True))
_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
_GAP: Final = r"[^a-z0-9]{0,3}"
_COMBINING_RE: Final = re.compile(
    "[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]"
)
_WHITESPACE_RE: Final = re.compile(r"\s+")
_DETECTOR_ERRORS: Final = (RuntimeError, ValueError, TypeError, OSError)


class VerificationAttempt:
    """Exactly one of: a verification result, or a storage/internal failure code."""

    __slots__ = ("failure", "result")

    def __init__(self, result: VerificationResult | None, failure: ErrorCode | None) -> None:
        if (result is None) == (failure is None):
            raise InvariantError("VerificationAttempt needs exactly one of result or failure")
        self.result = result
        self.failure = failure


class VerificationService:
    __slots__ = ("_clock", "_detector", "_docx", "_inputs", "_outputs", "_pdf")

    def __init__(
        self,
        inputs: InputStore,
        outputs: OutputStore,
        detector: DocumentDetector,
        clock: Clock,
        *,
        pdf: OutputInspector | None = None,
        docx: OutputInspector | None = None,
    ) -> None:
        self._inputs = inputs
        self._outputs = outputs
        self._detector = detector
        self._clock = clock
        self._pdf = pdf
        self._docx = docx

    def verify(
        self,
        source: StoredObject,
        output: StoredObject,
        source_document: ExtractedDocument,
        detection: DetectionOutcome,
        policy: MaskingPolicy,
    ) -> VerificationAttempt:
        """``source_document`` and ``detection`` are the in-memory results the output
        was produced from; only the source values are taken from them."""
        if detection.failure is not None:
            raise InvariantError("verification needs a successful detection outcome")
        fmt = source.document_format
        if output.document_format is not fmt or source_document.document_format is not fmt:
            raise InvariantError("verification formats do not match")
        inspector = self._inspector(fmt)
        try:
            source_bytes = self._read(self._inputs, source)
            output_bytes = self._read(self._outputs, output)
        except StorageError as error:
            logger.info("verification input unavailable")
            return VerificationAttempt(None, error.code)
        try:
            inspection = inspector.inspect(output_bytes, source_bytes)
        except InspectionError:
            logger.info("verification source unreadable")
            return VerificationAttempt(None, ErrorCode.INTERNAL_ERROR)
        failures = set(inspection.failures)
        review = False
        document = inspection.document
        if document is not None:
            redacted = policy.redacted_types
            if _values_remain(source_document, detection, redacted, document, inspection.raw):
                failures.add(ErrorCode.VERIFY_RESIDUAL_FINDING)
            if _words_remain_in_boxes(detection, redacted, document):
                failures.add(ErrorCode.VERIFY_RESIDUAL_FINDING)
            if _docx_text_differs(source_document, detection, redacted, document):
                failures.add(ErrorCode.VERIFY_RESIDUAL_FINDING)
            try:
                certain, uncertain = self._rerun(document, redacted)
            except _DETECTOR_ERRORS:
                logger.info("verification detector failed")
                return VerificationAttempt(None, ErrorCode.INTERNAL_ERROR)
            if certain:
                failures.add(ErrorCode.VERIFY_RESIDUAL_DETECTION)
            review = uncertain > 0
        if failures:
            outcome = VerificationOutcome.FAILED
        elif review:
            outcome = VerificationOutcome.REVIEW_REQUIRED
        else:
            outcome = VerificationOutcome.PASSED
        result = VerificationResult(
            outcome=outcome,
            failure_codes=frozenset(failures),
            output_ref=output.ref,
            verifier_id=VERIFIER_ID,
            verifier_version=VERIFIER_VERSION,
            verified_at=self._clock.now(),
        )
        logger.info(
            "verification outcome=%s codes=%s",
            outcome.value,
            ",".join(sorted(code.value for code in failures)) or "none",
        )
        return VerificationAttempt(result, None)

    def _inspector(self, fmt: DocumentFormat) -> OutputInspector:
        inspector = self._pdf if fmt is DocumentFormat.PDF else self._docx
        if inspector is None:
            raise InvariantError("verification has no inspector for this document format")
        return inspector

    @staticmethod
    def _read(store: InputStore | OutputStore, stored: StoredObject) -> bytes:
        store.verify(stored)
        with store.open(stored.ref, stored.document_format) as handle:
            return handle.read()

    def _rerun(
        self, document: ExtractedDocument, redacted: frozenset[EntityType]
    ) -> tuple[int, int]:
        certain = uncertain = 0
        for match in self._detector.detect(document).matches:
            if match.entity_type not in redacted or match.confidence < DISCARD_THRESHOLD:
                continue
            part = _part(document, match.page_number, match.part_name)
            if part is None or _is_label_only(part.text[match.start : match.end]):
                continue
            if match.confidence >= REDACT_THRESHOLD:
                certain += 1
            else:
                uncertain += 1
        return certain, uncertain


def fold(text: str) -> str:
    """NFC-insensitive, diacritic-free, case-folded view for value matching."""
    stripped = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return stripped.casefold().replace("đ", "d")


def value_pattern(entity_type: EntityType, value: str) -> re.Pattern[str] | None:
    """A pattern for one source value in folded text, or None if it is too
    generic to search for without matching unrelated kept text."""
    tokens = _TOKEN_RE.findall(fold(value))
    if sum(len(token) for token in tokens) < MIN_SEARCHED_CHARS:
        return None
    if entity_type in _NAME_TYPES:
        searched = len(tokens) >= 2
    elif entity_type in _NUMBERED_TYPES:
        searched = any(char.isdigit() for char in value) and (
            entity_type is EntityType.DATE_OF_BIRTH or len(tokens) >= 3
        )
    else:
        searched = entity_type in _SHAPE_TYPES
    if not searched:
        return None
    body = _GAP.join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _values_remain(
    source: ExtractedDocument,
    detection: DetectionOutcome,
    redacted: frozenset[EntityType],
    output: ExtractedDocument,
    raw: tuple[str, ...],
) -> bool:
    text = fold("\n".join(part.text for part in output.parts))
    folded_raw = tuple(fold(item) for item in raw)
    for pattern in _source_patterns(source, detection, redacted):
        if pattern.search(text) or any(pattern.search(item) for item in folded_raw):
            return True
    return False


def _source_patterns(
    source: ExtractedDocument, detection: DetectionOutcome, redacted: frozenset[EntityType]
) -> Iterator[re.Pattern[str]]:
    for match in detection.matches:
        if match.entity_type not in redacted:
            continue
        part = _part(source, match.page_number, match.part_name)
        if part is None or match.end > len(part.text):
            raise InvariantError("a detection match is outside its source part")
        pattern = value_pattern(match.entity_type, part.text[match.start : match.end])
        if pattern is not None:
            yield pattern


def _words_remain_in_boxes(
    detection: DetectionOutcome, redacted: frozenset[EntityType], output: ExtractedDocument
) -> bool:
    for finding in detection.findings:
        location = finding.location
        if finding.entity_type not in redacted or not isinstance(location, PdfLocation):
            continue
        part = _part(output, location.page_number, None)
        if part is None:
            return True
        for span in part.spans:
            if any(_centre_inside(word, location.boxes) for word in span.boxes) and not (
                _is_label_only(part.text[span.start : span.end])
            ):
                return True
    return False


def _docx_text_differs(
    source: ExtractedDocument,
    detection: DetectionOutcome,
    redacted: frozenset[EntityType],
    output: ExtractedDocument,
) -> bool:
    kept = [finding for finding in detection.findings if finding.entity_type in redacted]
    ranges = build_docx_ranges(kept)
    for part in source.parts:
        if part.part_name is None:
            continue
        expected = part.text
        for item in sorted(
            (r for r in ranges if r.part_name == part.part_name),
            key=lambda r: r.start,
            reverse=True,
        ):
            expected = expected[: item.start] + item.replacement_label + expected[item.end :]
        actual = _part(output, None, part.part_name)
        if actual is None or _squeeze(actual.text) != _squeeze(expected):
            return True
    return False


def _squeeze(text: str) -> str:
    return _WHITESPACE_RE.sub("", text)


def _centre_inside(word: BoundingBox, boxes: Iterable[BoundingBox]) -> bool:
    x = (word.x0 + word.x1) / 2
    y = (word.y0 + word.y1) / 2
    return any(box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1 for box in boxes)


def _is_label_only(text: str) -> bool:
    for label in _LABELS:
        text = text.replace(label, " ")
    return not any(char.isalnum() for char in text)


def _part(
    document: ExtractedDocument, page_number: int | None, part_name: str | None
) -> TextPart | None:
    for part in document.parts:
        if page_number is not None and part.page_number == page_number:
            return part
        if part_name is not None and part.part_name == part_name:
            return part
    return None
