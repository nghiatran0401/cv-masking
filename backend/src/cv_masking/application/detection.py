"""Run detectors, apply policy thresholds, and place findings. Text is never stored.

A document fails to review when any finding is uncertain, when no candidate
name was found (a CV always names its candidate), or when a PDF finding's
boxes are ambiguous. It fails outright (``MAP_FAILED``) when any finding cannot
be placed on its page or part at all.
"""

import logging
from uuid import uuid4

from cv_masking.application.mapping import build_docx_ranges, build_regions, map_span
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import (
    MAX_BOXES_PER_FINDING,
    DocxLocation,
    DocxRedactionRange,
    EntityFinding,
    FindingCounts,
    FindingLocation,
    PdfLocation,
    RedactionRegion,
)
from cv_masking.domain.ids import FindingId
from cv_masking.domain.policy import (
    DISCARD_THRESHOLD,
    REDACT_THRESHOLD,
    REPLACEMENT_LABELS,
    EntityType,
    MaskingPolicy,
)
from cv_masking.ports.detection import DetectionResult, DocumentDetector, TextMatch
from cv_masking.ports.extraction import ExtractedDocument, TextPart

logger = logging.getLogger("cv_masking.detection")


class DetectionOutcome:
    __slots__ = (
        "docx_ranges",
        "failure",
        "findings",
        "matches",
        "regions",
        "review",
        "suppressed_low_confidence",
    )

    def __init__(
        self,
        findings: tuple[EntityFinding, ...],
        matches: tuple[TextMatch, ...],
        suppressed_low_confidence: int,
        review: frozenset[ReviewReason],
        failure: ErrorCode | None = None,
        regions: tuple[RedactionRegion, ...] = (),
        docx_ranges: tuple[DocxRedactionRange, ...] = (),
    ) -> None:
        self.findings = findings
        self.matches = matches
        self.suppressed_low_confidence = suppressed_low_confidence
        self.review = review
        self.failure = failure
        self.regions = regions
        self.docx_ranges = docx_ranges

    @property
    def counts(self) -> FindingCounts:
        """One per detected entity: a long match split into several findings counts once."""
        totals: dict[EntityType, int] = {}
        for match in self.matches:
            totals[match.entity_type] = totals.get(match.entity_type, 0) + 1
        return FindingCounts.from_mapping(totals)


class DetectionService:
    __slots__ = ("_detector",)

    def __init__(self, detector: DocumentDetector) -> None:
        self._detector = detector

    def detect(self, document: ExtractedDocument, policy: MaskingPolicy) -> DetectionOutcome:
        """Find and place entities.

        Salary findings are always returned and counted. Regions and DOCX ranges, and the
        low-confidence and ambiguous-mapping reviews, cover only the types the
        policy redacts.
        """
        try:
            raw = self._detector.detect(document)
        except (RuntimeError, ValueError, TypeError, OSError):
            logger.info("detection failed")
            return DetectionOutcome((), (), 0, frozenset(), ErrorCode.DETECT_FAILED)
        kept, suppressed = _apply_thresholds(raw)
        findings: list[EntityFinding] = []
        ambiguous = 0
        for match in kept:
            placed = _place(match, document)
            if placed is None:
                logger.info("mapping failed matches=%d", len(kept))
                return DetectionOutcome((), (), suppressed, frozenset(), ErrorCode.MAP_FAILED)
            locations, is_ambiguous = placed
            ambiguous += int(is_ambiguous and match.entity_type in policy.redacted_types)
            findings.extend(_finding(match, location) for location in locations)
        redacted = [item for item in findings if item.entity_type in policy.redacted_types]
        review: set[ReviewReason] = set()
        if any(item.requires_review for item in redacted):
            review.add(ReviewReason.DETECT_LOW_CONFIDENCE)
        if not any(item.entity_type is EntityType.CANDIDATE_NAME for item in findings):
            review.add(ReviewReason.DETECT_NO_CANDIDATE_NAME)
        if ambiguous:
            review.add(ReviewReason.MAP_AMBIGUOUS)
        regions = build_regions(redacted)
        docx_ranges = build_docx_ranges(redacted)
        logger.info(
            "detection findings=%d suppressed=%d ambiguous=%d regions=%d review=%d",
            len(findings),
            suppressed,
            ambiguous,
            len(regions) + len(docx_ranges),
            len(review),
        )
        return DetectionOutcome(
            tuple(findings),
            kept,
            suppressed,
            frozenset(review),
            regions=regions,
            docx_ranges=docx_ranges,
        )


def _apply_thresholds(result: DetectionResult) -> tuple[tuple[TextMatch, ...], int]:
    kept: list[TextMatch] = []
    suppressed = 0
    for match in result.matches:
        if match.confidence < DISCARD_THRESHOLD:
            suppressed += 1
            continue
        kept.append(match)
    return tuple(kept), suppressed


def _place(
    match: TextMatch, document: ExtractedDocument
) -> tuple[tuple[FindingLocation, ...], bool] | None:
    """Locations for one match (a long PDF match may need several), and whether
    its boxes are ambiguous. None means the match cannot be placed."""
    part = _part_for(match, document)
    if part is None or match.end > len(part.text):
        return None
    if match.part_name is not None:
        return (DocxLocation(match.part_name, match.start, match.end),), False
    if match.page_number is None:
        return None
    mapped = map_span(part, match.start, match.end)
    if mapped is None:
        return None
    chunks = tuple(
        PdfLocation(match.page_number, mapped.boxes[index : index + MAX_BOXES_PER_FINDING])
        for index in range(0, len(mapped.boxes), MAX_BOXES_PER_FINDING)
    )
    return chunks, mapped.ambiguous


def _finding(match: TextMatch, location: FindingLocation) -> EntityFinding:
    return EntityFinding(
        finding_id=FindingId(uuid4()),
        entity_type=match.entity_type,
        location=location,
        confidence=match.confidence,
        detector_id=match.detector_id,
        detector_version=match.detector_version,
        replacement_label=REPLACEMENT_LABELS[match.entity_type],
        requires_review=DISCARD_THRESHOLD <= match.confidence < REDACT_THRESHOLD,
    )


def _part_for(match: TextMatch, document: ExtractedDocument) -> TextPart | None:
    for part in document.parts:
        if match.part_name is not None and part.part_name == match.part_name:
            return part
        if match.page_number is not None and part.page_number == match.page_number:
            return part
    return None
