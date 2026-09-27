"""Format-neutral detector output. Transient only: never persisted or logged."""

from dataclasses import dataclass
from typing import Protocol

from cv_masking.domain._validation import (
    require_finite_float,
    require_identifier,
    require_int,
    require_semver,
)
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES
from cv_masking.domain.policy import EntityType
from cv_masking.ports.extraction import ExtractedDocument


@dataclass(frozen=True, slots=True)
class TextMatch:
    """A character range on one extracted part. Never carries the matched text."""

    entity_type: EntityType
    start: int
    end: int
    confidence: float
    detector_id: str
    detector_version: str
    page_number: int | None = None
    part_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, EntityType):
            raise InvariantError("TextMatch.entity_type must be an EntityType")
        require_int(self.start, "TextMatch.start", minimum=0)
        require_int(self.end, "TextMatch.end", minimum=1)
        if self.end <= self.start:
            raise InvariantError("TextMatch.end must be greater than start")
        score = require_finite_float(self.confidence, "TextMatch.confidence")
        if not 0.0 <= score <= 1.0:
            raise InvariantError("TextMatch.confidence must be between 0 and 1")
        require_identifier(self.detector_id, "TextMatch.detector_id")
        require_semver(self.detector_version, "TextMatch.detector_version")
        has_page = self.page_number is not None
        has_part = self.part_name is not None
        if has_page == has_part:
            raise InvariantError("TextMatch needs either page_number or part_name")
        if has_page:
            require_int(
                self.page_number, "TextMatch.page_number", minimum=1, maximum=HARD_MAX_PDF_PAGES
            )


@dataclass(frozen=True, slots=True)
class DetectionResult:
    matches: tuple[TextMatch, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.matches, tuple) or not all(
            isinstance(match, TextMatch) for match in self.matches
        ):
            raise InvariantError("DetectionResult.matches must contain TextMatch values")


class DocumentDetector(Protocol):
    def detect(self, document: ExtractedDocument) -> DetectionResult:
        """Find Stage 7 entities. Never logs or stores document text."""
        ...
