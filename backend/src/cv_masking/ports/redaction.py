"""Format redactors: permanent removal into new output bytes. Never logs or stores text."""

from dataclasses import dataclass
from typing import Final, Protocol

from cv_masking.domain._validation import require_int
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import DocxRedactionRange, RedactionRegion

REDACTION_ERROR_CODES: Final = frozenset(
    {
        ErrorCode.REDACT_FAILED,
        ErrorCode.REDACT_SANITIZE_FAILED,
        ErrorCode.REDACT_OUTPUT_WRITE_FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Exactly one of: output bytes, or a failure code. Counts only, never text."""

    output: bytes | None = None
    failure: ErrorCode | None = None
    labelled_regions: int = 0
    solid_regions: int = 0

    def __post_init__(self) -> None:
        if (self.output is None) == (self.failure is None):
            raise InvariantError("RedactionResult needs exactly one of output or failure")
        if self.output is not None and (not isinstance(self.output, bytes) or not self.output):
            raise InvariantError("RedactionResult.output must be non-empty bytes")
        if self.failure is not None and self.failure not in REDACTION_ERROR_CODES:
            raise InvariantError("RedactionResult.failure must be a redaction error code")
        require_int(self.labelled_regions, "RedactionResult.labelled_regions", minimum=0)
        require_int(self.solid_regions, "RedactionResult.solid_regions", minimum=0)
        if self.failure is not None and (self.labelled_regions or self.solid_regions):
            raise InvariantError("a failed RedactionResult has no region counts")


class DocumentRedactor[Unit](Protocol):
    """``Unit`` is what one format redacts: PDF regions or DOCX character ranges."""

    def redact(self, data: bytes, units: tuple[Unit, ...]) -> RedactionResult:
        """Return new output bytes; ``data`` is never modified.

        Every hidden-content category is always removed (D-32); content that
        cannot be removed safely fails with REDACT_SANITIZE_FAILED.
        """
        ...


type PdfRedactor = DocumentRedactor[RedactionRegion]
type DocxRedactor = DocumentRedactor[DocxRedactionRange]
