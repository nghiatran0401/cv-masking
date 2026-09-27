"""Hidden-content categories and alerts. Alerts never carry text or names."""

from dataclasses import dataclass
from enum import StrEnum

from cv_masking.domain._validation import require_int
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES


class HiddenContentCategory(StrEnum):
    EMBEDDED_FILES = "embedded_files"
    FORMS = "forms"
    JAVASCRIPT = "javascript"
    ANNOTATIONS = "annotations"
    OPTIONAL_CONTENT = "optional_content"
    INVISIBLE_TEXT = "invisible_text"


@dataclass(frozen=True, slots=True)
class HiddenContentAlert:
    """What HR sees: kind, count, and page numbers. Never contents or names."""

    category: HiddenContentCategory
    count: int
    pages: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.category, HiddenContentCategory):
            raise InvariantError("HiddenContentAlert.category must be a HiddenContentCategory")
        require_int(self.count, "HiddenContentAlert.count", minimum=1)
        if not isinstance(self.pages, tuple) or not self.pages:
            raise InvariantError("HiddenContentAlert.pages must be a non-empty tuple")
        if self.pages != tuple(sorted(set(self.pages))):
            raise InvariantError("HiddenContentAlert.pages must be sorted and unique")
        for page in self.pages:
            require_int(page, "HiddenContentAlert page", minimum=1, maximum=HARD_MAX_PDF_PAGES)
