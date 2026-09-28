"""Messages between the API process and the worker: JSON headers plus a raw output frame.

The worker parses untrusted documents, so its replies are never unpickled:
each reply is plain JSON that is rebuilt through the domain constructors, which
re-check every invariant. Messages carry only IDs, hashes, codes, counts, and
the redacted output bytes; never document text.
"""

import json
from datetime import datetime
from typing import Final
from uuid import UUID

from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.errors import DomainError
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory, HiddenContentCounts
from cv_masking.domain.ids import ObjectRef, Sha256Digest
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.processing import ProcessingReport, ValidationReport, VerificationReport
from cv_masking.ports.storage import StoredObject

MAX_HEADER_BYTES: Final = 64 * 1024

type Json = dict[str, object]


class CodecError(Exception):
    """A message is malformed. Carries no message content."""


def encode(message: Json) -> bytes:
    return json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode(raw: bytes) -> Json:
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise CodecError from error
    if not isinstance(message, dict):
        raise CodecError
    return message


def _field[T](message: Json, name: str, kind: type[T]) -> T:
    value = message.get(name)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise CodecError
    return value


def _optional_code(message: Json) -> ErrorCode | None:
    value = message.get("failure")
    return None if value is None else ErrorCode(_field(message, "failure", str))


def _reasons(message: Json) -> frozenset[ReviewReason]:
    return frozenset(ReviewReason(_str(item)) for item in _field(message, "review", list))


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise CodecError
    return value


def _pairs(value: object) -> list[tuple[str, int]]:
    if not isinstance(value, list):
        raise CodecError
    pairs: list[tuple[str, int]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], int)
            or isinstance(item[1], bool)
        ):
            raise CodecError
        pairs.append((item[0], item[1]))
    return pairs


# ------------------------------------------------------------------ requests (API → worker)


def stored_to_json(stored: StoredObject) -> Json:
    return {
        "ref": str(stored.ref),
        "format": stored.document_format.value,
        "sha256": stored.sha256.value,
        "size": stored.size_bytes,
    }


def stored_from_json(message: Json) -> StoredObject:
    try:
        return StoredObject(
            ObjectRef(UUID(_field(message, "ref", str))),
            DocumentFormat(_field(message, "format", str)),
            Sha256Digest(_field(message, "sha256", str)),
            _field(message, "size", int),
        )
    except (DomainError, ValueError) as error:
        raise CodecError from error


def policy_to_json(policy: MaskingPolicy) -> Json:
    return {"mask_salary": policy.mask_salary, "version": policy.version}


def policy_from_json(message: Json) -> MaskingPolicy:
    try:
        return MaskingPolicy(
            mask_salary=_field(message, "mask_salary", bool),
            version=_field(message, "version", str),
        )
    except (DomainError, ValueError) as error:
        raise CodecError from error


# ------------------------------------------------------------------ replies (worker → API)


def validation_to_json(report: ValidationReport) -> Json:
    return {
        "failure": None if report.failure is None else report.failure.value,
        "review": sorted(reason.value for reason in report.review),
        "hidden": [[category.value, count] for category, count in report.hidden_removed.items],
    }


def validation_from_json(message: Json) -> ValidationReport:
    try:
        return ValidationReport(
            failure=_optional_code(message),
            review=_reasons(message),
            hidden_removed=HiddenContentCounts(
                tuple(
                    (HiddenContentCategory(name), count)
                    for name, count in _pairs(message.get("hidden"))
                )
            ),
        )
    except (DomainError, ValueError) as error:
        raise CodecError from error


def processing_to_json(report: ProcessingReport) -> Json:
    counts = report.finding_counts
    return {
        "failure": None if report.failure is None else report.failure.value,
        "review": sorted(reason.value for reason in report.review),
        "counts": None if counts is None else [[t.value, n] for t, n in counts.items],
        "output": report.output is not None,
    }


def processing_from_json(message: Json, output: bytes | None) -> ProcessingReport:
    try:
        raw_counts = message.get("counts")
        counts = (
            None
            if raw_counts is None
            else FindingCounts(tuple((EntityType(name), n) for name, n in _pairs(raw_counts)))
        )
        return ProcessingReport(
            output=output,
            failure=_optional_code(message),
            finding_counts=counts,
            review=_reasons(message),
        )
    except (DomainError, ValueError) as error:
        raise CodecError from error


def verification_to_json(report: VerificationReport) -> Json:
    result = report.result
    return {
        "failure": None if report.failure is None else report.failure.value,
        "result": None
        if result is None
        else {
            "outcome": result.outcome.value,
            "codes": sorted(code.value for code in result.failure_codes),
            "output_ref": str(result.output_ref),
            "verifier_id": result.verifier_id,
            "verifier_version": result.verifier_version,
            "verified_at": result.verified_at.isoformat(),
        },
    }


def verification_from_json(message: Json) -> VerificationReport:
    try:
        raw = message.get("result")
        result = None
        if raw is not None:
            if not isinstance(raw, dict):
                raise CodecError
            result = VerificationResult(
                outcome=VerificationOutcome(_field(raw, "outcome", str)),
                failure_codes=frozenset(ErrorCode(_str(c)) for c in _field(raw, "codes", list)),
                output_ref=ObjectRef(UUID(_field(raw, "output_ref", str))),
                verifier_id=_field(raw, "verifier_id", str),
                verifier_version=_field(raw, "verifier_version", str),
                verified_at=datetime.fromisoformat(_field(raw, "verified_at", str)),
            )
        return VerificationReport(result=result, failure=_optional_code(message))
    except (DomainError, ValueError) as error:
        raise CodecError from error
