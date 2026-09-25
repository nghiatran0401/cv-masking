"""Translation between domain objects and SQLite rows.

Rows are rebuilt through the domain constructors, which re-check every
invariant, so an impossible or tampered row fails closed with
STORAGE_INTEGRITY_FAILED instead of being loaded.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from cv_masking.domain.batch import Batch, BatchState
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import DomainError
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import BatchId, DocumentId, ObjectRef, Sha256Digest
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.storage import StorageError

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND: Final = timedelta(microseconds=1)

BATCH_COLUMNS: Final = (
    "batch_id",
    "state",
    "mask_salary",
    "document_count",
    "created_at",
    "updated_at",
    "version",
)
DOCUMENT_COLUMNS: Final = (
    "document_id",
    "batch_id",
    "state",
    "created_at",
    "updated_at",
    "version",
    "document_format",
    "input_ref",
    "content_sha256",
    "size_bytes",
    "uploaded_at",
    "attempt",
    "policy_mask_salary",
    "policy_version",
    "hidden_content_approved",
    "findings_review_approved",
    "output_ref",
    "finding_counts_recorded",
    "verification_outcome",
    "verifier_id",
    "verifier_version",
    "verified_at",
    "error_code",
)

type Row = dict[str, object]


@contextmanager
def decoding() -> Iterator[None]:
    """Turn any malformed stored value into a safe integrity failure."""
    try:
        yield
    except (DomainError, ValueError, TypeError, KeyError) as error:
        raise StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED) from error


def to_micros(value: datetime) -> int:
    return (value - _EPOCH) // _MICROSECOND


def _from_micros(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("timestamp must be an integer")
    return _EPOCH + value * _MICROSECOND


def _optional_micros(value: datetime | None) -> int | None:
    return None if value is None else to_micros(value)


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _from_micros(value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected text")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer")
    return value


def _flag(value: object) -> bool:
    if value not in (0, 1) or isinstance(value, bool):
        raise ValueError("expected 0 or 1")
    return value == 1


def _uuid(value: object) -> UUID:
    text = _text(value)
    parsed = UUID(text)
    if str(parsed) != text:
        raise ValueError("UUID is not in canonical form")
    return parsed


def _optional_ref(value: object) -> ObjectRef | None:
    return None if value is None else ObjectRef(_uuid(value))


def as_row(row: sqlite3.Row) -> Row:
    return {key: row[key] for key in row.keys()}  # noqa: SIM118 - sqlite3.Row is not a mapping


# ------------------------------------------------------------------ batches


def batch_params(batch: Batch) -> tuple[object, ...]:
    return (
        str(batch.batch_id),
        batch.state.value,
        int(batch.mask_salary),
        batch.document_count,
        to_micros(batch.created_at),
        to_micros(batch.updated_at),
        batch.version,
    )


def batch_from_row(row: Row) -> Batch:
    with decoding():
        return Batch(
            batch_id=BatchId(_uuid(row["batch_id"])),
            state=BatchState(_text(row["state"])),
            mask_salary=_flag(row["mask_salary"]),
            document_count=_integer(row["document_count"]),
            created_at=_from_micros(row["created_at"]),
            updated_at=_from_micros(row["updated_at"]),
            version=_integer(row["version"]),
        )


# ------------------------------------------------------------------ documents


def document_params(job: DocumentJob) -> tuple[object, ...]:
    verification = job.verification
    return (
        str(job.document_id),
        str(job.batch_id),
        job.state.value,
        to_micros(job.created_at),
        to_micros(job.updated_at),
        job.version,
        None if job.document_format is None else job.document_format.value,
        None if job.input_ref is None else str(job.input_ref),
        None if job.content_sha256 is None else job.content_sha256.value,
        job.size_bytes,
        _optional_micros(job.uploaded_at),
        job.attempt,
        None if job.policy is None else int(job.policy.mask_salary),
        None if job.policy is None else job.policy.version,
        int(job.hidden_content_approved),
        int(job.findings_review_approved),
        None if job.output_ref is None else str(job.output_ref),
        int(job.finding_counts is not None),
        None if verification is None else verification.outcome.value,
        None if verification is None else verification.verifier_id,
        None if verification is None else verification.verifier_version,
        None if verification is None else to_micros(verification.verified_at),
        None if job.error_code is None else job.error_code.value,
    )


def finding_count_params(job: DocumentJob) -> list[tuple[str, str, int]]:
    if job.finding_counts is None:
        return []
    return [
        (str(job.document_id), entity.value, count) for entity, count in job.finding_counts.items
    ]


def review_reason_params(job: DocumentJob) -> list[tuple[str, str]]:
    return [(str(job.document_id), reason.value) for reason in sorted(job.review_reasons)]


def verification_failure_params(job: DocumentJob) -> list[tuple[str, str]]:
    if job.verification is None:
        return []
    return [(str(job.document_id), code.value) for code in sorted(job.verification.failure_codes)]


def _policy(row: Row) -> MaskingPolicy | None:
    mask_salary, version = row["policy_mask_salary"], row["policy_version"]
    if mask_salary is None and version is None:
        return None
    return MaskingPolicy(mask_salary=_flag(mask_salary), version=_text(version))


def _finding_counts(row: Row, counts: list[Row]) -> FindingCounts | None:
    recorded = _flag(row["finding_counts_recorded"])
    if not recorded:
        if counts:
            raise ValueError("finding counts stored without the recorded flag")
        return None
    by_type = {EntityType(_text(item["entity_type"])): _integer(item["count"]) for item in counts}
    if len(by_type) != len(counts):
        raise ValueError("duplicate finding count")
    return FindingCounts.from_mapping(by_type)


def _verification(row: Row, failures: list[Row]) -> VerificationResult | None:
    fields = ("verification_outcome", "verifier_id", "verifier_version", "verified_at")
    if all(row[name] is None for name in fields):
        if failures:
            raise ValueError("verification failures stored without a verification")
        return None
    output_ref = _optional_ref(row["output_ref"])
    if output_ref is None:
        raise ValueError("verification stored without an output")
    return VerificationResult(
        outcome=VerificationOutcome(_text(row["verification_outcome"])),
        failure_codes=frozenset(ErrorCode(_text(item["code"])) for item in failures),
        output_ref=output_ref,
        verifier_id=_text(row["verifier_id"]),
        verifier_version=_text(row["verifier_version"]),
        verified_at=_from_micros(row["verified_at"]),
    )


def document_from_rows(
    row: Row, counts: list[Row], reasons: list[Row], failures: list[Row]
) -> DocumentJob:
    with decoding():
        size = row["size_bytes"]
        document_format = _optional_text(row["document_format"])
        sha256 = _optional_text(row["content_sha256"])
        error_code = _optional_text(row["error_code"])
        return DocumentJob(
            document_id=DocumentId(_uuid(row["document_id"])),
            batch_id=BatchId(_uuid(row["batch_id"])),
            state=DocumentState(_text(row["state"])),
            created_at=_from_micros(row["created_at"]),
            updated_at=_from_micros(row["updated_at"]),
            version=_integer(row["version"]),
            document_format=None if document_format is None else DocumentFormat(document_format),
            input_ref=_optional_ref(row["input_ref"]),
            content_sha256=None if sha256 is None else Sha256Digest(sha256),
            size_bytes=None if size is None else _integer(size),
            uploaded_at=_optional_datetime(row["uploaded_at"]),
            attempt=_integer(row["attempt"]),
            policy=_policy(row),
            hidden_content_approved=_flag(row["hidden_content_approved"]),
            findings_review_approved=_flag(row["findings_review_approved"]),
            output_ref=_optional_ref(row["output_ref"]),
            finding_counts=_finding_counts(row, counts),
            review_reasons=frozenset(ReviewReason(_text(item["reason"])) for item in reasons),
            verification=_verification(row, failures),
            error_code=None if error_code is None else ErrorCode(error_code),
        )


def document_state(value: object) -> DocumentState:
    with decoding():
        return DocumentState(_text(value))


def document_format(value: object) -> DocumentFormat:
    with decoding():
        return DocumentFormat(_text(value))


def object_ref(value: object) -> ObjectRef:
    with decoding():
        return ObjectRef(_uuid(value))
