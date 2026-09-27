"""Run detectors and apply policy thresholds. Text is never stored.

A document fails to review when any finding is uncertain, when no candidate
name was found (a CV always names its candidate), or when a match cannot be
placed on the page.
"""

import logging
from uuid import uuid4

from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import DocxLocation, EntityFinding, FindingCounts, PdfLocation
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
    __slots__ = ("failure", "findings", "matches", "review", "suppressed_low_confidence")

    def __init__(
        self,
        findings: tuple[EntityFinding, ...],
        matches: tuple[TextMatch, ...],
        suppressed_low_confidence: int,
        review: frozenset[ReviewReason],
        failure: ErrorCode | None = None,
    ) -> None:
        self.findings = findings
        self.matches = matches
        self.suppressed_low_confidence = suppressed_low_confidence
        self.review = review
        self.failure = failure

    @property
    def counts(self) -> FindingCounts:
        totals: dict[EntityType, int] = {}
        for finding in self.findings:
            totals[finding.entity_type] = totals.get(finding.entity_type, 0) + 1
        return FindingCounts.from_mapping(totals)


class DetectionService:
    __slots__ = ("_detector",)

    def __init__(self, detector: DocumentDetector) -> None:
        self._detector = detector

    def detect(self, document: ExtractedDocument, policy: MaskingPolicy) -> DetectionOutcome:
        """Find entities. Salary is always returned; policy does not hide it."""
        del policy
        try:
            raw = self._detector.detect(document)
        except (RuntimeError, ValueError, TypeError, OSError):
            logger.info("detection failed")
            return DetectionOutcome((), (), 0, frozenset(), ErrorCode.DETECT_FAILED)
        kept, suppressed = _apply_thresholds(raw)
        located = [(match, _to_finding(match, document)) for match in kept]
        findings = tuple(finding for _, finding in located if finding is not None)
        review: set[ReviewReason] = set()
        if any(item.requires_review for item in findings):
            review.add(ReviewReason.DETECT_LOW_CONFIDENCE)
        if not any(item.entity_type is EntityType.CANDIDATE_NAME for item in findings):
            review.add(ReviewReason.DETECT_NO_CANDIDATE_NAME)
        if any(finding is None for _, finding in located):
            review.add(ReviewReason.MAP_AMBIGUOUS)
        logger.info(
            "detection findings=%d suppressed=%d review=%d",
            len(findings),
            suppressed,
            len(review),
        )
        return DetectionOutcome(findings, kept, suppressed, frozenset(review))


def _apply_thresholds(result: DetectionResult) -> tuple[tuple[TextMatch, ...], int]:
    kept: list[TextMatch] = []
    suppressed = 0
    for match in result.matches:
        if match.confidence < DISCARD_THRESHOLD:
            suppressed += 1
            continue
        kept.append(match)
    return tuple(kept), suppressed


def _to_finding(match: TextMatch, document: ExtractedDocument) -> EntityFinding | None:
    part = _part_for(match, document)
    if part is None:
        return None
    location: DocxLocation | PdfLocation
    if match.part_name is not None:
        location = DocxLocation(match.part_name, match.start, match.end)
    else:
        boxes = tuple(
            box
            for span in part.spans
            if span.start < match.end and span.end > match.start
            for box in span.boxes
        )
        if not boxes or match.page_number is None:
            return None
        location = PdfLocation(match.page_number, boxes)
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
