"""Format inspectors for independent output verification. Transient only: never logged."""

from dataclasses import dataclass
from typing import Final, Protocol

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.ports.extraction import ExtractedDocument

INSPECTION_CODES: Final = frozenset(
    {
        ErrorCode.VERIFY_OUTPUT_INVALID,
        ErrorCode.VERIFY_PAGE_COUNT_MISMATCH,
        ErrorCode.VERIFY_STRUCTURE_MISMATCH,
        ErrorCode.VERIFY_RESIDUAL_METADATA,
    }
)


class InspectionError(Exception):
    """The source could not be read for comparison; not a finding about the output."""


@dataclass(frozen=True, slots=True)
class OutputInspection:
    """What a fresh parser sees in one output.

    ``document`` is all text the parser can extract, including text a reader
    cannot see; it is None when the output does not open. ``raw`` holds the
    decoded bytes of every non-font, non-image object and stream, for a plain
    value search. ``failures`` are the structural problems found.
    """

    document: ExtractedDocument | None
    raw: tuple[str, ...]
    failures: frozenset[ErrorCode]

    def __post_init__(self) -> None:
        if not isinstance(self.failures, frozenset) or not self.failures <= INSPECTION_CODES:
            raise InvariantError("OutputInspection.failures must be inspection codes")
        if self.document is None and ErrorCode.VERIFY_OUTPUT_INVALID not in self.failures:
            raise InvariantError("an output with no document must be VERIFY_OUTPUT_INVALID")
        if not isinstance(self.raw, tuple) or not all(isinstance(item, str) for item in self.raw):
            raise InvariantError("OutputInspection.raw must be a tuple of strings")


class OutputInspector(Protocol):
    def inspect(self, output: bytes, source: bytes) -> OutputInspection:
        """Open ``output`` and ``source`` with fresh parser handles and compare them.

        Raises InspectionError only when ``source`` itself cannot be read.
        """
        ...
