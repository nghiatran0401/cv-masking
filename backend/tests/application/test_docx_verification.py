"""Stage 11b: independent verification of redacted DOCX files, including tampered outputs."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import pytest
import synthetic_docx_redaction as fixture
from domain_builders import COUNTS, later, processing
from service_helpers import ManualClock
from synthetic_docx_verification import (
    INVALID_TAMPERS,
    METADATA_TAMPERS,
    STYLES_REMOVED_CLEANLY,
    UNUSED_HIDING_STYLE,
    VALUE_TAMPERS,
    Parts,
    tampered,
    zip_bomb,
)

from cv_masking.adapters.detection import PatternDetector, PresidioDetector
from cv_masking.adapters.docx import DocxVerifier, DocxXmlRedactor
from cv_masking.adapters.docx.archive import read_docx_archive
from cv_masking.adapters.docx.text import parse_xml, text_part_names, walk_part
from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.application import DetectionOutcome, DetectionService, VerificationService
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.extraction import ExtractedDocument, TextPart
from cv_masking.ports.storage import ObjectSink, StoredObject

_CATEGORIES = tuple(fixture.HIDDEN_BUILDERS)


@dataclass
class _Run:
    source: StoredObject
    output: StoredObject
    document: ExtractedDocument
    detection: DetectionOutcome
    policy: MaskingPolicy
    redacted: bytes


def _source_document(data: bytes) -> ExtractedDocument:
    """The text model detection runs on; built with the shared walk because the
    Stage 6b extractor still returns a review for hidden content until Stage 12."""
    parts = read_docx_archive(data)
    return ExtractedDocument(
        DocumentFormat.DOCX,
        tuple(
            TextPart(walk_part(parse_xml(parts[name])).text, (), part_name=name)
            for name in text_part_names(parts)
        ),
    )


def _store_output(output_store: LocalOutputStore, data: bytes) -> StoredObject:
    def produce(sink: ObjectSink) -> None:
        sink.write(data)

    return output_store.save(DocumentFormat.DOCX, produce, max_bytes=HARD_MAX_FILE_BYTES)


def _run(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    *,
    data: bytes | None = None,
    policy: MaskingPolicy | None = None,
    output: bytes | None = None,
) -> _Run:
    chosen = policy or MaskingPolicy()
    source_bytes = data if data is not None else fixture.cv_docx()
    document = _source_document(source_bytes)
    detection = DetectionService(PresidioDetector()).detect(document, chosen)
    result = DocxXmlRedactor().redact(source_bytes, detection.docx_ranges)
    assert result.output is not None
    source = input_store.save_stream(
        DocumentFormat.DOCX, [source_bytes], max_bytes=HARD_MAX_FILE_BYTES
    )
    stored = _store_output(output_store, output if output is not None else result.output)
    return _Run(source, stored, document, detection, chosen, result.output)


def _verify(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    run: _Run,
    policy: MaskingPolicy | None = None,
) -> VerificationResult:
    service = VerificationService(
        input_store, output_store, PatternDetector(), ManualClock(), docx=DocxVerifier()
    )
    attempt = service.verify(
        run.source, run.output, run.document, run.detection, policy or run.policy
    )
    assert attempt.failure is None
    assert attempt.result is not None
    return attempt.result


def _codes(result: VerificationResult) -> set[str]:
    return {code.value for code in result.failure_codes}


def _tampered(
    input_store: LocalInputStore, output_store: LocalOutputStore, change: Callable[[Parts], None]
) -> VerificationResult:
    clean = _run(input_store, output_store)
    run = _run(input_store, output_store, output=tampered(clean.redacted, change))
    return _verify(input_store, output_store, run)


# ------------------------------------------------------------------ passing outputs


def test_a_redacted_docx_passes_and_neither_file_changes(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    run = _run(input_store, output_store)
    paths = [
        root.path / "inputs" / f"{run.source.ref.value}.docx",
        root.path / "outputs" / f"{run.output.ref.value}.docx",
    ]
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    result = _verify(input_store, output_store, run)
    assert result.outcome is VerificationOutcome.PASSED
    assert result.output_ref == run.output.ref
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == before


@pytest.mark.parametrize("categories", [*((name,) for name in _CATEGORIES), _CATEGORIES])
def test_outputs_with_hidden_content_removed_pass(
    input_store: LocalInputStore, output_store: LocalOutputStore, categories: tuple[str, ...]
) -> None:
    run = _run(input_store, output_store, data=fixture.with_hidden(*categories))
    assert _verify(input_store, output_store, run).outcome is VerificationOutcome.PASSED


def test_salary_left_by_the_toggle_is_not_a_leak(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store, policy=MaskingPolicy(mask_salary=False))
    assert _verify(input_store, output_store, run).outcome is VerificationOutcome.PASSED
    on = _verify(input_store, output_store, run, policy=MaskingPolicy())
    assert on.outcome is VerificationOutcome.FAILED


def test_an_unused_style_that_hides_text_is_allowed(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    result = _tampered(input_store, output_store, UNUSED_HIDING_STYLE)
    assert result.outcome is VerificationOutcome.PASSED


# ------------------------------------------------------------------ tampered outputs


def test_the_unredacted_input_as_output_fails(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store, output=fixture.cv_docx())
    result = _verify(input_store, output_store, run)
    assert {
        "VERIFY_RESIDUAL_FINDING",
        "VERIFY_RESIDUAL_DETECTION",
        "VERIFY_RESIDUAL_METADATA",
    } <= _codes(result)
    assert result.primary_failure_code is ErrorCode.VERIFY_RESIDUAL_FINDING


@pytest.mark.parametrize("tamper", list(VALUE_TAMPERS), ids=list(VALUE_TAMPERS))
def test_residue_in_any_part_is_a_residual_finding(
    input_store: LocalInputStore, output_store: LocalOutputStore, tamper: str
) -> None:
    result = _tampered(input_store, output_store, VALUE_TAMPERS[tamper])
    assert result.outcome is VerificationOutcome.FAILED
    assert "VERIFY_RESIDUAL_FINDING" in _codes(result)


@pytest.mark.parametrize("tamper", list(METADATA_TAMPERS), ids=list(METADATA_TAMPERS))
def test_always_stripped_and_hidden_content_are_caught(
    input_store: LocalInputStore, output_store: LocalOutputStore, tamper: str
) -> None:
    result = _tampered(input_store, output_store, METADATA_TAMPERS[tamper])
    assert result.outcome is VerificationOutcome.FAILED
    assert "VERIFY_RESIDUAL_METADATA" in _codes(result)


@pytest.mark.parametrize(
    "tamper",
    ["document_properties", "comments", "field_code", "thumbnail", "alt_text", "hyperlink_target"],
)
def test_residue_outside_the_text_is_also_residual_metadata(
    input_store: LocalInputStore, output_store: LocalOutputStore, tamper: str
) -> None:
    result = _tampered(input_store, output_store, VALUE_TAMPERS[tamper])
    assert "VERIFY_RESIDUAL_METADATA" in _codes(result)


def test_a_missing_part_is_a_structure_mismatch(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    result = _tampered(input_store, output_store, STYLES_REMOVED_CLEANLY)
    assert _codes(result) == {"VERIFY_STRUCTURE_MISMATCH"}


@pytest.mark.parametrize("tamper", list(INVALID_TAMPERS), ids=list(INVALID_TAMPERS))
def test_a_broken_package_is_invalid(
    input_store: LocalInputStore, output_store: LocalOutputStore, tamper: str
) -> None:
    result = _tampered(input_store, output_store, INVALID_TAMPERS[tamper])
    assert _codes(result) == {"VERIFY_OUTPUT_INVALID"}


@pytest.mark.parametrize(
    "damage",
    [
        lambda data: data[: len(data) // 2],
        lambda data: b"not a zip",
        lambda data: bytes.fromhex("d0cf11e0a1b11ae1") + data,
        lambda data: zip_bomb(),
    ],
    ids=["truncated", "not_zip", "ole_container", "zip_bomb"],
)
def test_an_output_that_does_not_open_safely_is_invalid(
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    damage: Callable[[bytes], bytes],
) -> None:
    clean = _run(input_store, output_store)
    run = _run(input_store, output_store, output=damage(clean.redacted))
    assert _codes(_verify(input_store, output_store, run)) == {"VERIFY_OUTPUT_INVALID"}


# ------------------------------------------------------------------ boundaries and job gate


def test_an_unreadable_source_is_an_internal_error(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    run = _run(input_store, output_store)
    broken = input_store.save_stream(
        DocumentFormat.DOCX, [b"PK synthetic broken"], max_bytes=HARD_MAX_FILE_BYTES
    )
    service = VerificationService(
        input_store, output_store, PatternDetector(), ManualClock(), docx=DocxVerifier()
    )
    attempt = service.verify(broken, run.output, run.document, run.detection, run.policy)
    assert attempt.failure is ErrorCode.INTERNAL_ERROR


def test_only_a_passed_verification_completes_a_docx_job(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    clean = _run(input_store, output_store)
    leaked = _run(input_store, output_store, output=fixture.cv_docx())
    for run, state in ((clean, DocumentState.COMPLETED), (leaked, DocumentState.FAILED)):
        job = processing(DocumentFormat.DOCX)
        job = job.output_written(run.output.ref, COUNTS, (), later(job))
        done = job.record_verification(_verify(input_store, output_store, run), later(job))
        assert done.state is state
    assert done.error_code is ErrorCode.VERIFY_RESIDUAL_FINDING
