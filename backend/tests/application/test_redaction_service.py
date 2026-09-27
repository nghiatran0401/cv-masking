"""Stage 10: RedactionService writes a new output and never changes the stored input."""

import hashlib
import logging
from pathlib import Path

import pytest
from synthetic_redaction import EMAIL, NAME, PHONE, all_text, cv_pdf

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor
from cv_masking.application import DetectionOutcome, DetectionService, RedactionService
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import RedactionRegion
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.ports.redaction import RedactionResult
from cv_masking.ports.storage import Producer, StorageError, StoredObject


class _FailingRedactor:
    def redact(
        self, data: bytes, regions: tuple[RedactionRegion, ...], *, remove_hidden: bool
    ) -> RedactionResult:
        return RedactionResult(failure=ErrorCode.REDACT_SANITIZE_FAILED)


class _FullOutputStore(LocalOutputStore):
    def save(
        self, document_format: DocumentFormat, producer: Producer, *, max_bytes: int
    ) -> StoredObject:
        raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)


class _TamperingRedactor:
    """Changes the stored input while redacting, as a buggy adapter might."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def redact(
        self, data: bytes, regions: tuple[RedactionRegion, ...], *, remove_hidden: bool
    ) -> RedactionResult:
        self._path.chmod(0o600)
        self._path.write_bytes(data + b"%tampered\n")
        return PyMuPDFRedactor().redact(data, regions, remove_hidden=remove_hidden)


def _stored(input_store: LocalInputStore, data: bytes) -> StoredObject:
    return input_store.save_stream(DocumentFormat.PDF, [data], max_bytes=HARD_MAX_FILE_BYTES)


def _detected(data: bytes) -> DetectionOutcome:
    document = PyMuPDFExtractor().extract(data).document
    assert document is not None
    return DetectionService(PresidioDetector()).detect(document, MaskingPolicy())


def _service(
    input_store: LocalInputStore, output_store: LocalOutputStore, redactor: object = None
) -> RedactionService:
    chosen = redactor if redactor is not None else PyMuPDFRedactor()
    return RedactionService(input_store, output_store, {DocumentFormat.PDF: chosen})  # type: ignore[dict-item]


def _entries(root: StorageRoot, kind: str) -> list[str]:
    return sorted(path.name for path in (root.path / kind).iterdir())


def test_output_is_a_new_object_and_the_input_hash_is_unchanged(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    input_path = root.path / "inputs" / f"{source.ref.value}.pdf"
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    outcome = _service(input_store, output_store).redact(
        source, _detected(data), remove_hidden=False
    )
    assert outcome.failure is None
    assert outcome.output is not None
    assert outcome.output.ref != source.ref
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == before
    assert before == source.sha256.value
    input_store.verify(source)
    output_store.verify(outcome.output)
    with output_store.open(outcome.output.ref, DocumentFormat.PDF) as handle:
        text = all_text(handle.read())
    leaked = [value in text for value in (NAME, EMAIL, PHONE)]
    assert not any(leaked), f"values leaked: {leaked.count(True)}"
    assert outcome.labelled_regions + outcome.solid_regions == len(_detected(data).regions)


def test_redactor_failure_is_reported_and_nothing_is_stored(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    outcome = _service(input_store, output_store, _FailingRedactor()).redact(
        source, _detected(data), remove_hidden=True
    )
    assert outcome.failure is ErrorCode.REDACT_SANITIZE_FAILED
    assert outcome.output is None
    assert _entries(root, "outputs") == []


def test_output_write_failure_is_a_redaction_code(
    input_store: LocalInputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    outcome = _service(input_store, _FullOutputStore(root)).redact(
        source, _detected(data), remove_hidden=False
    )
    assert outcome.failure is ErrorCode.REDACT_OUTPUT_WRITE_FAILED
    assert _entries(root, "outputs") == []


def test_a_tampered_input_is_refused_before_reading(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    path = root.path / "inputs" / f"{source.ref.value}.pdf"
    path.chmod(0o600)
    path.write_bytes(data + b"%tampered\n")
    outcome = _service(input_store, output_store).redact(
        source, _detected(data), remove_hidden=False
    )
    assert outcome.failure is ErrorCode.STORAGE_INTEGRITY_FAILED
    assert _entries(root, "outputs") == []


def test_an_input_changed_during_redaction_deletes_the_output(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    path = root.path / "inputs" / f"{source.ref.value}.pdf"
    outcome = _service(input_store, output_store, _TamperingRedactor(path)).redact(
        source, _detected(data), remove_hidden=False
    )
    assert outcome.failure is ErrorCode.STORAGE_INTEGRITY_FAILED
    assert _entries(root, "outputs") == []


def test_a_failed_detection_cannot_be_redacted(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    source = _stored(input_store, cv_pdf())
    failed = DetectionOutcome((), (), 0, frozenset(), ErrorCode.MAP_FAILED)
    with pytest.raises(InvariantError, match="successful detection"):
        _service(input_store, output_store).redact(source, failed, remove_hidden=False)


def test_a_format_without_a_redactor_is_refused(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    source = input_store.save_stream(DocumentFormat.DOCX, [b"PK synthetic"], max_bytes=1000)
    service = _service(input_store, output_store)
    with pytest.raises(InvariantError, match="no redactor"):
        service.redact(source, _detected(cv_pdf()), remove_hidden=False)


def test_service_logs_counts_only(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        _service(input_store, output_store).redact(source, _detected(data), remove_hidden=False)
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "redaction written regions=" in logged
    for index, value in enumerate((*NAME.split(), EMAIL, PHONE, str(source.ref.value))):
        found = value in logged
        assert not found, f"value {index} logged"
