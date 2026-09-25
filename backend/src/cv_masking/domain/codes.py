"""Closed sets of safe error codes and review reasons.

Kept in sync with docs/error-codes.md by tests/domain/test_codes.py.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from cv_masking.domain.formats import DocumentFormat


class ErrorCode(StrEnum):
    """A reason a document ended in FAILED (or CANCELLED), or a request was refused."""

    UPLOAD_UNSUPPORTED_TYPE = "UPLOAD_UNSUPPORTED_TYPE"
    UPLOAD_SPOOFED_TYPE = "UPLOAD_SPOOFED_TYPE"
    DOCX_MACRO_OR_TEMPLATE = "DOCX_MACRO_OR_TEMPLATE"
    UPLOAD_FILE_TOO_LARGE = "UPLOAD_FILE_TOO_LARGE"
    UPLOAD_BATCH_FILE_LIMIT = "UPLOAD_BATCH_FILE_LIMIT"
    UPLOAD_BATCH_SIZE_LIMIT = "UPLOAD_BATCH_SIZE_LIMIT"
    UPLOAD_DUPLICATE = "UPLOAD_DUPLICATE"
    UPLOAD_MALFORMED_REQUEST = "UPLOAD_MALFORMED_REQUEST"
    UPLOAD_TIMEOUT = "UPLOAD_TIMEOUT"
    UPLOAD_BATCH_CLOSED = "UPLOAD_BATCH_CLOSED"

    PDF_MALFORMED = "PDF_MALFORMED"
    PDF_NO_PAGES = "PDF_NO_PAGES"
    PDF_RESOURCE_LIMIT = "PDF_RESOURCE_LIMIT"

    DOCX_MALFORMED = "DOCX_MALFORMED"
    DOCX_UNSAFE_ARCHIVE = "DOCX_UNSAFE_ARCHIVE"
    DOCX_RESOURCE_LIMIT = "DOCX_RESOURCE_LIMIT"

    DETECT_FAILED = "DETECT_FAILED"
    MAP_FAILED = "MAP_FAILED"

    REDACT_FAILED = "REDACT_FAILED"
    REDACT_SANITIZE_FAILED = "REDACT_SANITIZE_FAILED"
    REDACT_OUTPUT_WRITE_FAILED = "REDACT_OUTPUT_WRITE_FAILED"

    VERIFY_OUTPUT_INVALID = "VERIFY_OUTPUT_INVALID"
    VERIFY_PAGE_COUNT_MISMATCH = "VERIFY_PAGE_COUNT_MISMATCH"
    VERIFY_STRUCTURE_MISMATCH = "VERIFY_STRUCTURE_MISMATCH"
    VERIFY_RESIDUAL_FINDING = "VERIFY_RESIDUAL_FINDING"
    VERIFY_RESIDUAL_DETECTION = "VERIFY_RESIDUAL_DETECTION"
    VERIFY_RESIDUAL_METADATA = "VERIFY_RESIDUAL_METADATA"

    JOB_TIMEOUT = "JOB_TIMEOUT"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_INTERRUPTED = "JOB_INTERRUPTED"
    JOB_EXPIRED = "JOB_EXPIRED"

    STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
    STORAGE_PATH_REJECTED = "STORAGE_PATH_REJECTED"
    STORAGE_INTEGRITY_FAILED = "STORAGE_INTEGRITY_FAILED"

    SECURITY_HOST_REJECTED = "SECURITY_HOST_REJECTED"
    SECURITY_ORIGIN_REJECTED = "SECURITY_ORIGIN_REJECTED"
    SECURITY_TOKEN_INVALID = "SECURITY_TOKEN_INVALID"  # noqa: S105 - code name, not a secret
    SECURITY_RATE_LIMITED = "SECURITY_RATE_LIMITED"

    INTERNAL_ERROR = "INTERNAL_ERROR"


class CodeGroup(StrEnum):
    UPLOAD = "upload"
    VALIDATION = "validation"
    PROCESSING = "processing"
    VERIFICATION = "verification"
    JOB = "job"
    STORAGE = "storage"
    SECURITY = "security"
    INTERNAL = "internal"


def _group(code: ErrorCode) -> CodeGroup:
    if code is ErrorCode.DOCX_MACRO_OR_TEMPLATE or code.startswith("UPLOAD_"):
        return CodeGroup.UPLOAD
    if code.startswith(("PDF_", "DOCX_")):
        return CodeGroup.VALIDATION
    if code.startswith(("DETECT_", "MAP_", "REDACT_")):
        return CodeGroup.PROCESSING
    if code.startswith("VERIFY_"):
        return CodeGroup.VERIFICATION
    if code.startswith("JOB_"):
        return CodeGroup.JOB
    if code.startswith("STORAGE_"):
        return CodeGroup.STORAGE
    if code.startswith("SECURITY_"):
        return CodeGroup.SECURITY
    return CodeGroup.INTERNAL


ERROR_CODE_GROUPS: Final[Mapping[ErrorCode, CodeGroup]] = MappingProxyType(
    {code: _group(code) for code in ErrorCode}
)

RETRYABLE_ERROR_CODES: Final = frozenset(
    {
        ErrorCode.UPLOAD_MALFORMED_REQUEST,
        ErrorCode.UPLOAD_TIMEOUT,
        ErrorCode.DETECT_FAILED,
        ErrorCode.MAP_FAILED,
        ErrorCode.REDACT_FAILED,
        ErrorCode.REDACT_SANITIZE_FAILED,
        ErrorCode.REDACT_OUTPUT_WRITE_FAILED,
        ErrorCode.JOB_TIMEOUT,
        ErrorCode.JOB_INTERRUPTED,
        ErrorCode.STORAGE_WRITE_FAILED,
        ErrorCode.SECURITY_RATE_LIMITED,
        ErrorCode.INTERNAL_ERROR,
    }
)


class ReviewReason(StrEnum):
    """A reason a document is held in REVIEW_REQUIRED."""

    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_TOO_MANY_PAGES = "PDF_TOO_MANY_PAGES"
    PDF_NO_TEXT_LAYER = "PDF_NO_TEXT_LAYER"
    PDF_TEXT_UNRELIABLE = "PDF_TEXT_UNRELIABLE"
    DOCX_ENCRYPTED = "DOCX_ENCRYPTED"
    DOCX_TOO_LARGE_TEXT = "DOCX_TOO_LARGE_TEXT"
    DOCX_NO_TEXT = "DOCX_NO_TEXT"
    PDF_HIDDEN_CONTENT = "PDF_HIDDEN_CONTENT"
    DOCX_HIDDEN_CONTENT = "DOCX_HIDDEN_CONTENT"
    DETECT_LOW_CONFIDENCE = "DETECT_LOW_CONFIDENCE"
    MAP_AMBIGUOUS = "MAP_AMBIGUOUS"
    VERIFY_REVIEW = "VERIFY_REVIEW"


class ReviewKind(StrEnum):
    BLOCKING = "blocking"
    """Unsupported input; HR can only delete."""
    HIDDEN_CONTENT = "hidden_content"
    """Approve removes the hidden content and continues processing."""
    FINDINGS = "findings"
    """Approve accepts an already-verified output with uncertain findings."""
    VERIFIER = "verifier"
    """The verifier could not decide; HR can only deny."""


REVIEW_REASON_KINDS: Final[Mapping[ReviewReason, ReviewKind]] = MappingProxyType(
    {
        ReviewReason.PDF_ENCRYPTED: ReviewKind.BLOCKING,
        ReviewReason.PDF_TOO_MANY_PAGES: ReviewKind.BLOCKING,
        ReviewReason.PDF_NO_TEXT_LAYER: ReviewKind.BLOCKING,
        ReviewReason.PDF_TEXT_UNRELIABLE: ReviewKind.BLOCKING,
        ReviewReason.DOCX_ENCRYPTED: ReviewKind.BLOCKING,
        ReviewReason.DOCX_TOO_LARGE_TEXT: ReviewKind.BLOCKING,
        ReviewReason.DOCX_NO_TEXT: ReviewKind.BLOCKING,
        ReviewReason.PDF_HIDDEN_CONTENT: ReviewKind.HIDDEN_CONTENT,
        ReviewReason.DOCX_HIDDEN_CONTENT: ReviewKind.HIDDEN_CONTENT,
        ReviewReason.DETECT_LOW_CONFIDENCE: ReviewKind.FINDINGS,
        ReviewReason.MAP_AMBIGUOUS: ReviewKind.FINDINGS,
        ReviewReason.VERIFY_REVIEW: ReviewKind.VERIFIER,
    }
)

VALIDATION_REVIEW_KINDS: Final = frozenset({ReviewKind.BLOCKING, ReviewKind.HIDDEN_CONTENT})
POST_PROCESSING_REVIEW_KINDS: Final = frozenset({ReviewKind.FINDINGS, ReviewKind.VERIFIER})

_FORMAT_SPECIFIC_ERRORS: Final[Mapping[ErrorCode, DocumentFormat]] = MappingProxyType(
    {
        **{code: DocumentFormat.PDF for code in ErrorCode if code.startswith("PDF_")},
        **{
            code: DocumentFormat.DOCX
            for code in ErrorCode
            if code.startswith("DOCX_") and code is not ErrorCode.DOCX_MACRO_OR_TEMPLATE
        },
        ErrorCode.VERIFY_PAGE_COUNT_MISMATCH: DocumentFormat.PDF,
        ErrorCode.VERIFY_STRUCTURE_MISMATCH: DocumentFormat.DOCX,
    }
)

_FORMAT_SPECIFIC_REASONS: Final[Mapping[ReviewReason, DocumentFormat]] = MappingProxyType(
    {
        **{r: DocumentFormat.PDF for r in ReviewReason if r.startswith("PDF_")},
        **{r: DocumentFormat.DOCX for r in ReviewReason if r.startswith("DOCX_")},
    }
)


def is_retryable(code: ErrorCode) -> bool:
    return code in RETRYABLE_ERROR_CODES


def error_format(code: ErrorCode) -> DocumentFormat | None:
    """The only document format this code can apply to, or None if format-neutral."""
    return _FORMAT_SPECIFIC_ERRORS.get(code)


def reason_format(reason: ReviewReason) -> DocumentFormat | None:
    return _FORMAT_SPECIFIC_REASONS.get(reason)
