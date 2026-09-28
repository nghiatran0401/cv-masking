"""Stage 10: RedactionService returns new output bytes and never changes the stored input.

Storing the output (and re-checking the input afterwards) is the worker's job
since Stage 12; see test_worker.py.
"""

import hashlib
import logging

import pytest
import synthetic_docx_redaction as docx_fixture
from synthetic_redaction import EMAIL, NAME, PHONE, all_text, cv_pdf

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.docx import DocxExtractor, DocxXmlRedactor
from cv_masking.adapters.local_storage import LocalInputStore, StorageRoot
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor
from cv_masking.application import DetectionOutcome, DetectionService, RedactionService
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import RedactionRegion
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.ports.redaction import RedactionResult
from cv_masking.ports.storage import StoredObject


class _FailingRedactor:
    def redact(self, data: bytes, regions: tuple[RedactionRegion, ...]) -> RedactionResult:
        return RedactionResult(failure=ErrorCode.REDACT_SANITIZE_FAILED)


def _stored(input_store: LocalInputStore, data: bytes) -> StoredObject:
    return input_store.save_stream(DocumentFormat.PDF, [data], max_bytes=HARD_MAX_FILE_BYTES)


def _detected(data: bytes) -> DetectionOutcome:
    document = PyMuPDFExtractor().extract(data).document
    assert document is not None
    return DetectionService(PresidioDetector()).detect(document, MaskingPolicy())


def _service(input_store: LocalInputStore, redactor: object = None) -> RedactionService:
    chosen = redactor if redactor is not None else PyMuPDFRedactor()
    return RedactionService(input_store, pdf=chosen)  # type: ignore[arg-type]


def _entries(root: StorageRoot, kind: str) -> list[str]:
    return sorted(path.name for path in (root.path / kind).iterdir())


def test_output_bytes_are_redacted_and_the_input_hash_is_unchanged(
    input_store: LocalInputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    input_path = root.path / "inputs" / f"{source.ref.value}.pdf"
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    outcome = _service(input_store).redact(source, _detected(data))
    assert outcome.failure is None
    assert outcome.output is not None
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == before == source.sha256.value
    input_store.verify(source)
    text = all_text(outcome.output)
    leaked = [value in text for value in (NAME, EMAIL, PHONE)]
    assert not any(leaked), f"values leaked: {leaked.count(True)}"
    assert outcome.labelled_regions + outcome.solid_regions == len(_detected(data).regions)
    assert _entries(root, "outputs") == []


def test_docx_output_is_redacted_and_the_input_hash_is_unchanged(
    input_store: LocalInputStore, root: StorageRoot
) -> None:
    data = docx_fixture.cv_docx()
    source = input_store.save_stream(DocumentFormat.DOCX, [data], max_bytes=HARD_MAX_FILE_BYTES)
    input_path = root.path / "inputs" / f"{source.ref.value}.docx"
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    document = DocxExtractor().extract(data).document
    assert document is not None
    detection = DetectionService(PresidioDetector()).detect(document, MaskingPolicy())
    assert detection.docx_ranges
    service = RedactionService(input_store, docx=DocxXmlRedactor())
    outcome = service.redact(source, detection)
    assert outcome.failure is None
    assert outcome.output is not None
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == before == source.sha256.value
    leaked = [
        docx_fixture.appears(value, outcome.output)
        for value in (docx_fixture.EMAIL, docx_fixture.PHONE)
    ]
    assert not any(leaked), f"values leaked: {leaked.count(True)}"
    assert outcome.labelled_regions == len(detection.docx_ranges)


def test_redactor_failure_is_reported(input_store: LocalInputStore) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    outcome = _service(input_store, _FailingRedactor()).redact(source, _detected(data))
    assert outcome.failure is ErrorCode.REDACT_SANITIZE_FAILED
    assert outcome.output is None


def test_a_tampered_input_is_refused_before_reading(
    input_store: LocalInputStore, root: StorageRoot
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    path = root.path / "inputs" / f"{source.ref.value}.pdf"
    path.chmod(0o600)
    path.write_bytes(data + b"%tampered\n")
    outcome = _service(input_store).redact(source, _detected(data))
    assert outcome.failure is ErrorCode.STORAGE_INTEGRITY_FAILED


def test_a_failed_detection_cannot_be_redacted(input_store: LocalInputStore) -> None:
    source = _stored(input_store, cv_pdf())
    failed = DetectionOutcome((), (), 0, frozenset(), ErrorCode.MAP_FAILED)
    with pytest.raises(InvariantError, match="successful detection"):
        _service(input_store).redact(source, failed)


def test_a_format_without_a_redactor_is_refused(input_store: LocalInputStore) -> None:
    source = input_store.save_stream(DocumentFormat.DOCX, [b"PK synthetic"], max_bytes=1000)
    with pytest.raises(InvariantError, match="no redactor"):
        _service(input_store).redact(source, _detected(cv_pdf()))


def test_service_logs_counts_only(
    input_store: LocalInputStore, caplog: pytest.LogCaptureFixture
) -> None:
    data = cv_pdf()
    source = _stored(input_store, data)
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        _service(input_store).redact(source, _detected(data))
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "redaction applied regions=" in logged
    for index, value in enumerate((*NAME.split(), EMAIL, PHONE, str(source.ref.value))):
        found = value in logged
        assert not found, f"value {index} logged"
