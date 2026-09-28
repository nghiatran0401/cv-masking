"""Hidden-content categories and alerts. Alerts never carry text or names."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from cv_masking.domain._validation import require_int
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES

_PART_KIND_RE: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")


class HiddenContentCategory(StrEnum):
    EMBEDDED_FILES = "embedded_files"
    FORMS = "forms"
    JAVASCRIPT = "javascript"
    ANNOTATIONS = "annotations"
    OPTIONAL_CONTENT = "optional_content"
    INVISIBLE_TEXT = "invisible_text"
    TRACKED_CHANGES = "tracked_changes"
    COMMENTS = "comments"
    HIDDEN_TEXT = "hidden_text"
    IMPORTED_CHUNKS = "imported_chunks"
    CUSTOM_XML = "custom_xml"
    GLOSSARY = "glossary"
    EXTERNAL_RELATIONSHIPS = "external_relationships"


@dataclass(frozen=True, slots=True)
class HiddenContentAlert:
    """What HR sees: kind, count, and pages or part types. Never contents or names."""

    category: HiddenContentCategory
    count: int
    pages: tuple[int, ...] = ()
    parts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.category, HiddenContentCategory):
            raise InvariantError("HiddenContentAlert.category must be a HiddenContentCategory")
        require_int(self.count, "HiddenContentAlert.count", minimum=1)
        if not isinstance(self.pages, tuple) or not isinstance(self.parts, tuple):
            raise InvariantError("HiddenContentAlert pages and parts must be tuples")
        if bool(self.pages) == bool(self.parts):
            raise InvariantError("HiddenContentAlert needs pages or parts, not both or neither")
        if self.pages:
            if self.pages != tuple(sorted(set(self.pages))):
                raise InvariantError("HiddenContentAlert.pages must be sorted and unique")
            for page in self.pages:
                require_int(page, "HiddenContentAlert page", minimum=1, maximum=HARD_MAX_PDF_PAGES)
            return
        if self.parts != tuple(sorted(set(self.parts))):
            raise InvariantError("HiddenContentAlert.parts must be sorted and unique")
        if not all(isinstance(part, str) and _PART_KIND_RE.fullmatch(part) for part in self.parts):
            raise InvariantError("HiddenContentAlert.parts must be lowercase identifiers")


@dataclass(frozen=True, slots=True)
class HiddenContentCounts:
    """How much of each hidden-content category was removed; what a job keeps (D-32)."""

    items: tuple[tuple[HiddenContentCategory, int], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise InvariantError("HiddenContentCounts.items must be a tuple")
        seen: list[HiddenContentCategory] = []
        for item in self.items:
            if not (isinstance(item, tuple) and len(item) == 2):
                raise InvariantError("HiddenContentCounts.items must be (category, count) pairs")
            category, count = item
            if not isinstance(category, HiddenContentCategory):
                raise InvariantError("HiddenContentCounts keys must be categories")
            require_int(count, "HiddenContentCounts count", minimum=1)
            seen.append(category)
        order = list(HiddenContentCategory)
        if seen != sorted(set(seen), key=order.index):
            raise InvariantError("HiddenContentCounts items must be unique and in category order")

    @classmethod
    def from_alerts(cls, alerts: Iterable[HiddenContentAlert]) -> "HiddenContentCounts":
        totals: dict[HiddenContentCategory, int] = {}
        for alert in alerts:
            totals[alert.category] = totals.get(alert.category, 0) + alert.count
        return cls(tuple((c, totals[c]) for c in HiddenContentCategory if c in totals))

    def as_dict(self) -> dict[HiddenContentCategory, int]:
        return dict(self.items)


NO_HIDDEN_CONTENT: Final = HiddenContentCounts()
