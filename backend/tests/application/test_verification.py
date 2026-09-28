"""Stage 11: independent verification of redacted PDFs, including tampered outputs."""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from domain_builders import COUNTS, later, processing
from service_helpers import ManualClock
from synthetic_redaction import EMAIL, HIDDEN_BUILDERS, NAME, PHONE, SALARY, cv_pdf, with_hidden
from synthetic_verification import (
    METADATA_TAMPERS,
    STRAY_WORD,
    VALUE_TAMPERS,
    incrementally_updated,
    tampered,
    with_extra_page,
    with_other_email,
    with_text_at,
)

from cv_masking.adapters.detection import PatternDetector, PresidioDetector
from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor, PyMuPDFVerifier
from cv_masking.application import DetectionOutcome, DetectionService, VerificationService
from cv_masking.application.verification import VERIFIER_ID, fold, value_pattern
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import PdfLocation
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.detection import DetectionResult, TextMatch
from cv_masking.ports.extraction import ExtractedDocument
from cv_masking.ports.storage import ObjectSink, StoredObject

_CATEGORIES = tuple(HIDDEN_BUILDERS)


@dataclass
class _Run:
    source: StoredObject
    output: StoredObject
    document: ExtractedDocument
    detection: DetectionOutcome
    policy: MaskingPolicy
    redacted: bytes


def _detect(data: bytes, policy: MaskingPolicy) -> tuple[ExtractedDocument, DetectionOutcome]:
    document = PyMuPDFExtractor().extract(data).document
    assert document is not None
    return document, DetectionService(PresidioDetector()).detect(document, policy)


def _store_output(output_store: LocalOutputStore, data: bytes) -> StoredObject:
    def produce(sink: ObjectSink) -> None:
        sink.write(data)

    return output_store.save(DocumentFormat.PDF, produce, max_bytes=HARD_MAX_FILE_BYTES)


def _run(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    *,
    data: bytes | None = None,
    policy: MaskingPolicy | None = None,
    output: bytes | None = None,
) -> _Run:
    """Detect on the clean CV, redact ``data`` (default: the clean CV), and store
    both; ``output`` replaces the redacted bytes with a tampered copy."""
    chosen = policy or MaskingPolicy()
    document, detection = _detect(cv_pdf(), chosen)
    source_bytes = data if data is not None else cv_pdf()
    result = PyMuPDFRedactor().redact(source_bytes, detection.regions)
    assert result.output is not None
    source = input_store.save_stream(
        DocumentFormat.PDF, [source_bytes], max_bytes=HARD_MAX_FILE_BYTES
    )
    stored = _store_output(output_store, output if output is not None else result.output)
    return _Run(source, stored, document, detection, chosen, result.output)


def _service(
    input_store: LocalInputStore, output_store: LocalOutputStore, detector: object = None
) -> VerificationService:
    return VerificationService(
        input_store,
        output_store,
        detector or PatternDetector(),  # type: ignore[arg-type]
        ManualClock(),
        pdf=PyMuPDFVerifier(),
    )


def _verify(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    run: _Run,
    detector: object = None,
    policy: MaskingPolicy | None = None,
) -> VerificationResult:
    attempt = _service(input_store, output_store, detector).verify(
        run.source, run.output, run.document, run.detection, policy or run.policy
    )
    assert attempt.failure is None
    assert attempt.result is not None
    return attempt.result


def _codes(result: VerificationResult) -> set[str]:
    return {code.value for code in result.failure_codes}


def _tampered_run(
    input_store: LocalInputStore, output_store: LocalOutputStore, change: object
) -> _Run:
    clean = _run(input_store, output_store)
    return _run(input_store, output_store, output=tampered(clean.redacted, change))  # type: ignore[arg-type]


# ------------------------------------------------------------------ passing outputs


def test_a_redacted_output_passes_and_neither_file_changes(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    run = _run(input_store, output_store)
    paths = [
        root.path / "inputs" / f"{run.source.ref.value}.pdf",
        root.path / "outputs" / f"{run.output.ref.value}.pdf",
    ]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    result = _verify(input_store, output_store, run)
    assert result.outcome is VerificationOutcome.PASSED
    assert result.failure_codes == frozenset()
    assert result.output_ref == run.output.ref
    assert result.verifier_id == VERIFIER_ID
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == before


@pytest.mark.parametrize("categories", [*((name,) for name in _CATEGORIES), _CATEGORIES])
def test_outputs_with_hidden_content_removed_pass(
    input_store: LocalInputStore, output_store: LocalOutputStore, categories: tuple[str, ...]
) -> None:
    run = _run(input_store, output_store, data=with_hidden(cv_pdf(), *categories))
    assert _verify(input_store, output_store, run).outcome is VerificationOutcome.PASSED


def test_salary_left_by_the_toggle_is_not_a_leak(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    off = MaskingPolicy(mask_salary=False)
    run = _run(input_store, output_store, policy=off)
    assert _verify(input_store, output_store, run).outcome is VerificationOutcome.PASSED
    on = _verify(input_store, output_store, run, policy=MaskingPolicy())
    assert on.outcome is VerificationOutcome.FAILED
    assert "VERIFY_RESIDUAL_DETECTION" in _codes(on)


# ------------------------------------------------------------------ tampered outputs


def test_the_unredacted_input_as_output_fails_on_every_text_check(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store, output=cv_pdf())
    result = _verify(input_store, output_store, run)
    assert result.outcome is VerificationOutcome.FAILED
    assert {"VERIFY_RESIDUAL_FINDING", "VERIFY_RESIDUAL_DETECTION"} <= _codes(result)
    assert result.primary_failure_code is ErrorCode.VERIFY_RESIDUAL_FINDING


@pytest.mark.parametrize("tamper", list(VALUE_TAMPERS), ids=list(VALUE_TAMPERS))
def test_a_source_value_put_back_is_a_residual_finding(
    input_store: LocalInputStore, output_store: LocalOutputStore, tamper: str
) -> None:
    run = _tampered_run(input_store, output_store, VALUE_TAMPERS[tamper])
    result = _verify(input_store, output_store, run)
    assert result.outcome is VerificationOutcome.FAILED
    assert "VERIFY_RESIDUAL_FINDING" in _codes(result)


@pytest.mark.parametrize("tamper", list(METADATA_TAMPERS), ids=list(METADATA_TAMPERS))
def test_metadata_attachments_links_and_hidden_content_are_caught(
    input_store: LocalInputStore, output_store: LocalOutputStore, tamper: str
) -> None:
    run = _tampered_run(input_store, output_store, METADATA_TAMPERS[tamper])
    result = _verify(input_store, output_store, run)
    assert result.outcome is VerificationOutcome.FAILED
    assert "VERIFY_RESIDUAL_METADATA" in _codes(result)


def test_any_word_inside_a_redacted_box_is_a_residual_finding(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    clean = _run(input_store, output_store)
    name = next(
        finding
        for finding in clean.detection.findings
        if finding.entity_type is EntityType.CANDIDATE_NAME
        and isinstance(finding.location, PdfLocation)
    )
    assert isinstance(name.location, PdfLocation)
    box = name.location.boxes[0]
    point = (box.x0 + 1, (box.y0 + box.y1) / 2 + 3)
    run = _run(input_store, output_store, output=with_text_at(clean.redacted, STRAY_WORD, point))
    result = _verify(input_store, output_store, run)
    assert _codes(result) == {"VERIFY_RESIDUAL_FINDING"}


def test_a_new_entity_is_a_residual_detection(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    clean = _run(input_store, output_store)
    run = _run(input_store, output_store, output=with_other_email(clean.redacted))
    assert _codes(_verify(input_store, output_store, run)) == {"VERIFY_RESIDUAL_DETECTION"}


def test_a_changed_page_count_is_caught(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    clean = _run(input_store, output_store)
    run = _run(input_store, output_store, output=with_extra_page(clean.redacted))
    assert _codes(_verify(input_store, output_store, run)) == {"VERIFY_PAGE_COUNT_MISMATCH"}


def test_an_incremental_update_is_residual_history(
    input_store: LocalInputStore, output_store: LocalOutputStore, tmp_path: Path
) -> None:
    clean = _run(input_store, output_store)
    updated = incrementally_updated(clean.redacted, tmp_path)
    run = _run(input_store, output_store, output=updated)
    assert "VERIFY_RESIDUAL_METADATA" in _codes(_verify(input_store, output_store, run))


@pytest.mark.parametrize(
    "damage",
    [
        lambda data: data[: len(data) // 2],
        lambda data: b"not a pdf at all",
        lambda data: b"%PDF-1.7\n",
    ],
    ids=["truncated", "not_pdf", "header_only"],
)
def test_an_output_that_does_not_open_is_invalid(
    input_store: LocalInputStore, output_store: LocalOutputStore, damage: object
) -> None:
    clean = _run(input_store, output_store)
    run = _run(input_store, output_store, output=damage(clean.redacted))  # type: ignore[operator]
    result = _verify(input_store, output_store, run)
    assert result.outcome is VerificationOutcome.FAILED
    assert _codes(result) == {"VERIFY_OUTPUT_INVALID"}


# ------------------------------------------------------------------ detector rerun rules


class _StubDetector:
    """Returns one match over ``target`` in the first output page."""

    def __init__(self, target: str, entity: EntityType, confidence: float) -> None:
        self._target = target
        self._entity = entity
        self._confidence = confidence

    def detect(self, document: ExtractedDocument) -> DetectionResult:
        text = document.parts[0].text
        start = text.index(self._target)
        match = TextMatch(
            self._entity,
            start,
            start + len(self._target),
            self._confidence,
            "test.stub",
            "1.0.0",
            page_number=1,
        )
        return DetectionResult((match,))


@pytest.mark.parametrize(
    ("target", "entity", "confidence", "outcome"),
    [
        ("[NAME]", EntityType.EMAIL, 0.95, VerificationOutcome.PASSED),
        ("Example", EntityType.EMAIL, 0.4, VerificationOutcome.PASSED),
        ("Example", EntityType.EMAIL, 0.6, VerificationOutcome.REVIEW_REQUIRED),
        ("Example", EntityType.EMAIL, 0.95, VerificationOutcome.FAILED),
    ],
    ids=["label_only", "discarded", "uncertain", "certain"],
)
def test_rerun_matches_follow_the_policy_thresholds(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    target: str,
    entity: EntityType,
    confidence: float,
    outcome: VerificationOutcome,
) -> None:
    run = _run(input_store, output_store)
    detector = _StubDetector(target, entity, confidence)
    assert _verify(input_store, output_store, run, detector).outcome is outcome


def test_rerun_matches_of_types_the_policy_keeps_are_ignored(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store, policy=MaskingPolicy(mask_salary=False))
    detector = _StubDetector("Example", EntityType.SALARY, 0.95)
    assert _verify(input_store, output_store, run, detector).outcome is VerificationOutcome.PASSED


def test_the_rerun_detector_uses_only_the_deterministic_rules() -> None:
    document, _ = _detect(cv_pdf(), MaskingPolicy())
    found = {match.entity_type for match in PatternDetector().detect(document).matches}
    assert {EntityType.EMAIL, EntityType.PHONE, EntityType.SALARY} <= found
    assert not found & {EntityType.CANDIDATE_NAME, EntityType.REFERENCE_NAME}


# ------------------------------------------------------------------ value search rules


@pytest.mark.parametrize(
    ("entity", "value", "searched"),
    [
        (EntityType.CANDIDATE_NAME, "Nguyễn Văn Mẫu", True),
        (EntityType.CANDIDATE_NAME, "Mẫu", False),
        (EntityType.EMAIL, "mau.nguyen@example.test", True),
        (EntityType.PHONE, "0900000000", True),
        (EntityType.PHONE, "090", False),
        (EntityType.DATE_OF_BIRTH, "01/01/1990", True),
        (EntityType.DATE_OF_BIRTH, "1990", False),
        (EntityType.POSTAL_ADDRESS, "12 Đường Ví Dụ, Quận Mẫu", True),
        (EntityType.POSTAL_ADDRESS, "Hà Nội, Việt Nam", False),
        (EntityType.NATIONALITY, "Việt Nam", False),
        (EntityType.GENDER, "Nam", False),
    ],
    ids=[
        "full_name",
        "single_name_token",
        "email",
        "phone",
        "short_digits",
        "full_date",
        "year_only",
        "numbered_address",
        "city_only_address",
        "nationality",
        "gender",
    ],
)
def test_only_distinctive_values_are_searched(
    entity: EntityType, value: str, searched: bool
) -> None:
    assert (value_pattern(entity, value) is not None) is searched


@pytest.mark.parametrize(
    "text",
    ["NGUYEN  VAN MAU", "nguyễn-văn-mẫu", "Nguye\u0302\u0303n Va\u0306n Ma\u0302\u0303u"],
    ids=["upper_extra_space", "hyphenated", "nfd"],
)
def test_name_search_is_normalized(text: str) -> None:
    pattern = value_pattern(EntityType.CANDIDATE_NAME, NAME)
    assert pattern is not None
    assert pattern.search(fold(text)) is not None


def test_name_search_respects_word_boundaries() -> None:
    pattern = value_pattern(EntityType.CANDIDATE_NAME, NAME)
    assert pattern is not None
    assert pattern.search(fold("xnguyen van mau")) is None


# ------------------------------------------------------------------ failures and boundaries


def test_a_tampered_stored_output_is_a_storage_failure(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    run = _run(input_store, output_store)
    path = root.path / "outputs" / f"{run.output.ref.value}.pdf"
    path.chmod(0o600)
    path.write_bytes(cv_pdf())
    attempt = _service(input_store, output_store).verify(
        run.source, run.output, run.document, run.detection, run.policy
    )
    assert attempt.result is None
    assert attempt.failure is ErrorCode.STORAGE_INTEGRITY_FAILED


def test_an_unreadable_source_is_an_internal_error(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store)
    broken = input_store.save_stream(
        DocumentFormat.PDF, [b"%PDF-synthetic broken"], max_bytes=HARD_MAX_FILE_BYTES
    )
    attempt = _service(input_store, output_store).verify(
        broken, run.output, run.document, run.detection, run.policy
    )
    assert attempt.failure is ErrorCode.INTERNAL_ERROR


def test_programming_errors_are_refused_before_any_io(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store)
    service = _service(input_store, output_store)
    failed = DetectionOutcome((), (), 0, frozenset(), ErrorCode.MAP_FAILED)
    with pytest.raises(InvariantError, match="successful detection"):
        service.verify(run.source, run.output, run.document, failed, run.policy)
    docx = input_store.save_stream(DocumentFormat.DOCX, [b"PK synthetic"], max_bytes=1000)
    with pytest.raises(InvariantError, match="formats do not match"):
        service.verify(docx, run.output, run.document, run.detection, run.policy)


def test_verification_logs_codes_only(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run = _run(input_store, output_store, output=cv_pdf())
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        _verify(input_store, output_store, run)
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "verification outcome=failed" in logged
    values = (*NAME.split(), EMAIL, PHONE, SALARY, str(run.source.ref.value))
    for index, value in enumerate(values):
        found = value in logged
        assert not found, f"value {index} logged"


# ------------------------------------------------------------------ job gate


def test_only_a_passed_verification_completes_the_job(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    clean = _run(input_store, output_store)
    leaked = _run(input_store, output_store, output=cv_pdf())
    for run, state in ((clean, DocumentState.COMPLETED), (leaked, DocumentState.FAILED)):
        job = processing()
        job = job.output_written(run.output.ref, COUNTS, (), later(job))
        result = _verify(input_store, output_store, run)
        done = job.record_verification(result, later(job))
        assert done.state is state
    assert done.error_code is ErrorCode.VERIFY_RESIDUAL_FINDING
