"""Processing port: the isolated place where one document is validated, redacted, and verified.

Parsing untrusted files and running detectors is CPU-heavy and may hang, so it
runs away from the API's event loop in a worker that can be stopped at any
time (D-33). The worker only reads stored files; every metadata change and
every stored output is written by the caller. A session holds one document's
transient text in the worker's memory and forgets it when it ends.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from cv_masking.domain.codes import (
    ERROR_CODE_GROUPS,
    REVIEW_REASON_KINDS,
    CodeGroup,
    ErrorCode,
    ReviewKind,
    ReviewReason,
)
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.hidden import NO_HIDDEN_CONTENT, HiddenContentCounts
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationResult
from cv_masking.ports.storage import StoredObject


def _require_reasons(reasons: object, kind: ReviewKind, name: str) -> None:
    if not isinstance(reasons, frozenset) or not all(
        isinstance(reason, ReviewReason) and REVIEW_REASON_KINDS[reason] is kind
        for reason in reasons
    ):
        raise InvariantError(f"{name} must be {kind} review reasons")


def _require_code(code: object, groups: frozenset[CodeGroup], name: str) -> None:
    if code is not None and (
        not isinstance(code, ErrorCode) or ERROR_CODE_GROUPS[code] not in groups
    ):
        raise InvariantError(f"{name} does not fit this step")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Exactly one of: passed (with what hidden content will be removed), a failure, or review."""

    failure: ErrorCode | None = None
    review: frozenset[ReviewReason] = frozenset()
    hidden_removed: HiddenContentCounts = NO_HIDDEN_CONTENT

    def __post_init__(self) -> None:
        _require_code(
            self.failure,
            frozenset({CodeGroup.VALIDATION, CodeGroup.STORAGE, CodeGroup.INTERNAL}),
            "ValidationReport.failure",
        )
        _require_reasons(self.review, ReviewKind.BLOCKING, "ValidationReport.review")
        if self.failure is not None and self.review:
            raise InvariantError("ValidationReport cannot both fail and need review")
        if not isinstance(self.hidden_removed, HiddenContentCounts):
            raise InvariantError("ValidationReport.hidden_removed must be HiddenContentCounts")
        if self.hidden_removed.items and not self.passed:
            raise InvariantError("only a passed validation reports hidden content")

    @property
    def passed(self) -> bool:
        return self.failure is None and not self.review


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    """Exactly one of: output bytes with counts and findings reasons, or a failure code."""

    output: bytes | None = None
    failure: ErrorCode | None = None
    finding_counts: FindingCounts | None = None
    review: frozenset[ReviewReason] = frozenset()

    def __post_init__(self) -> None:
        _require_code(
            self.failure,
            frozenset({CodeGroup.PROCESSING, CodeGroup.STORAGE, CodeGroup.INTERNAL}),
            "ProcessingReport.failure",
        )
        _require_reasons(self.review, ReviewKind.FINDINGS, "ProcessingReport.review")
        if (self.output is None) == (self.failure is None):
            raise InvariantError("ProcessingReport needs exactly one of output or failure")
        if self.output is not None:
            if not isinstance(self.output, bytes) or not 1 <= len(self.output) <= (
                HARD_MAX_FILE_BYTES
            ):
                raise InvariantError("ProcessingReport.output must be bounded, non-empty bytes")
            if not isinstance(self.finding_counts, FindingCounts):
                raise InvariantError("ProcessingReport needs finding counts with an output")
        elif self.finding_counts is not None or self.review:
            raise InvariantError("a failed ProcessingReport has no counts or reasons")


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Exactly one of: a verification result, or a storage/internal failure code."""

    result: VerificationResult | None = None
    failure: ErrorCode | None = None

    def __post_init__(self) -> None:
        _require_code(
            self.failure,
            frozenset({CodeGroup.STORAGE, CodeGroup.INTERNAL}),
            "VerificationReport.failure",
        )
        if (self.result is None) == (self.failure is None):
            raise InvariantError("VerificationReport needs exactly one of result or failure")
        if self.result is not None and not isinstance(self.result, VerificationResult):
            raise InvariantError("VerificationReport.result must be a VerificationResult")


class ProcessingError(Exception):
    """The worker did not answer. Carries no document data."""


class ProcessingTimeoutError(ProcessingError):
    """The document used up its time budget; the worker was stopped (JOB_TIMEOUT)."""


class ProcessingCrashedError(ProcessingError):
    """The worker died, failed to start, or sent an unreadable reply."""


class ProcessingStoppedError(ProcessingError):
    """The worker was shut down while it held the document (JOB_INTERRUPTED)."""


class ProcessingSession(Protocol):
    """One document, in order: validate, then process, then verify."""

    def validate(self, source: StoredObject) -> ValidationReport: ...

    def process(self, policy: MaskingPolicy) -> ProcessingReport: ...

    def verify(self, output: StoredObject) -> VerificationReport: ...


class ProcessingPipeline(ProcessingSession, Protocol):
    """What runs inside the worker; reused for every document."""

    def forget(self) -> None:
        """Drop the current document's text and findings."""
        ...


class DocumentProcessor(Protocol):
    def session(self) -> AbstractContextManager[ProcessingSession]:
        """A ready worker for one document; its time budget starts now.

        Raises ProcessingCrashedError if no worker can be started.
        """
        ...

    def close(self) -> None:
        """Stop the worker; a call in progress raises ProcessingStoppedError."""
        ...
