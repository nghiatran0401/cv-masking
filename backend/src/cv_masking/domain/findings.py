"""Entity findings and their locations.

A finding records *where* an entity is and *what type* it is, never its text.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from cv_masking.domain._validation import (
    require_bool,
    require_finite_float,
    require_identifier,
    require_int,
    require_semver,
)
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.ids import FindingId
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES
from cv_masking.domain.policy import REPLACEMENT_LABELS, EntityType

MAX_BOXES_PER_FINDING: Final = 64
MAX_BOXES_PER_REGION: Final = 512
_DOCX_PART_RE: Final = re.compile(r"word/[a-z][a-z0-9]{0,31}\.xml")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Rectangle in PDF page coordinates (points)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        x0 = require_finite_float(self.x0, "BoundingBox.x0")
        y0 = require_finite_float(self.y0, "BoundingBox.y0")
        x1 = require_finite_float(self.x1, "BoundingBox.x1")
        y1 = require_finite_float(self.y1, "BoundingBox.y1")
        if not (x0 < x1 and y0 < y1):
            raise InvariantError("BoundingBox must have positive width and height")


@dataclass(frozen=True, slots=True)
class PdfLocation:
    page_number: int
    boxes: tuple[BoundingBox, ...]

    def __post_init__(self) -> None:
        require_int(
            self.page_number, "PdfLocation.page_number", minimum=1, maximum=HARD_MAX_PDF_PAGES
        )
        if not isinstance(self.boxes, tuple) or not self.boxes:
            raise InvariantError("PdfLocation.boxes must be a non-empty tuple")
        if len(self.boxes) > MAX_BOXES_PER_FINDING:
            raise InvariantError("PdfLocation.boxes has too many boxes")
        if not all(isinstance(box, BoundingBox) for box in self.boxes):
            raise InvariantError("PdfLocation.boxes must contain BoundingBox values")


@dataclass(frozen=True, slots=True)
class DocxLocation:
    """Half-open character range [start, end) in the extracted text of one DOCX part."""

    part_name: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.part_name, str) or _DOCX_PART_RE.fullmatch(self.part_name) is None:
            raise InvariantError("DocxLocation.part_name must look like word/<name>.xml")
        require_int(self.start, "DocxLocation.start", minimum=0)
        require_int(self.end, "DocxLocation.end", minimum=1)
        if self.end <= self.start:
            raise InvariantError("DocxLocation.end must be greater than start")


type FindingLocation = PdfLocation | DocxLocation


@dataclass(frozen=True, slots=True)
class EntityFinding:
    finding_id: FindingId
    entity_type: EntityType
    location: FindingLocation
    confidence: float
    detector_id: str
    detector_version: str
    replacement_label: str
    requires_review: bool

    def __post_init__(self) -> None:
        if not isinstance(self.finding_id, FindingId):
            raise InvariantError("EntityFinding.finding_id must be a FindingId")
        if not isinstance(self.entity_type, EntityType):
            raise InvariantError("EntityFinding.entity_type must be an EntityType")
        if not isinstance(self.location, PdfLocation | DocxLocation):
            raise InvariantError("EntityFinding.location must be a PdfLocation or DocxLocation")
        confidence = require_finite_float(self.confidence, "EntityFinding.confidence")
        if not 0.0 <= confidence <= 1.0:
            raise InvariantError("EntityFinding.confidence must be between 0 and 1")
        require_identifier(self.detector_id, "EntityFinding.detector_id")
        require_semver(self.detector_version, "EntityFinding.detector_version")
        if self.replacement_label != REPLACEMENT_LABELS[self.entity_type]:
            raise InvariantError(
                "EntityFinding.replacement_label must match the policy label for its type"
            )
        require_bool(self.requires_review, "EntityFinding.requires_review")


@dataclass(frozen=True, slots=True)
class RedactionRegion:
    """One PDF redaction area: overlapping findings merged, one label for the whole region.

    The label is the highest-priority member type (masking-policy.md §5). Boxes
    are never unioned across lines, so a region never covers unrelated words.
    """

    page_number: int
    boxes: tuple[BoundingBox, ...]
    entity_type: EntityType
    finding_ids: tuple[FindingId, ...]

    def __post_init__(self) -> None:
        require_int(
            self.page_number, "RedactionRegion.page_number", minimum=1, maximum=HARD_MAX_PDF_PAGES
        )
        if not isinstance(self.boxes, tuple) or not self.boxes:
            raise InvariantError("RedactionRegion.boxes must be a non-empty tuple")
        if len(self.boxes) > MAX_BOXES_PER_REGION:
            raise InvariantError("RedactionRegion.boxes has too many boxes")
        if not all(isinstance(box, BoundingBox) for box in self.boxes):
            raise InvariantError("RedactionRegion.boxes must contain BoundingBox values")
        if not isinstance(self.entity_type, EntityType):
            raise InvariantError("RedactionRegion.entity_type must be an EntityType")
        if (
            not isinstance(self.finding_ids, tuple)
            or not self.finding_ids
            or not all(isinstance(item, FindingId) for item in self.finding_ids)
            or len(set(self.finding_ids)) != len(self.finding_ids)
        ):
            raise InvariantError("RedactionRegion.finding_ids must be unique FindingId values")

    @property
    def replacement_label(self) -> str:
        return REPLACEMENT_LABELS[self.entity_type]


@dataclass(frozen=True, slots=True)
class FindingCounts:
    """Number of findings per entity type; the only finding data a job keeps."""

    items: tuple[tuple[EntityType, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise InvariantError("FindingCounts.items must be a tuple")
        seen: set[EntityType] = set()
        for item in self.items:
            if not (isinstance(item, tuple) and len(item) == 2):
                raise InvariantError("FindingCounts.items must contain (type, count) pairs")
            entity_type, count = item
            if not isinstance(entity_type, EntityType):
                raise InvariantError("FindingCounts keys must be EntityType values")
            if entity_type in seen:
                raise InvariantError("FindingCounts keys must be unique")
            seen.add(entity_type)
            require_int(count, "FindingCounts count", minimum=0)
        order = list(EntityType)
        if [entity for entity, _ in self.items] != sorted(seen, key=order.index):
            raise InvariantError("FindingCounts items must be in EntityType order")

    @classmethod
    def from_mapping(cls, counts: Mapping[EntityType, int]) -> "FindingCounts":
        return cls(tuple((entity, counts[entity]) for entity in EntityType if entity in counts))

    def as_dict(self) -> dict[EntityType, int]:
        return dict(self.items)

    @property
    def total(self) -> int:
        return sum(count for _, count in self.items)
