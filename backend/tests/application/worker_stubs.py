"""Stub pipelines for worker tests; imported by name inside the spawned worker process.

A stub reads the stored synthetic input and behaves according to its first
line, so one factory covers every outcome and a replaced worker behaves the
same as the first. Inputs are synthetic marker bytes, never document text.
"""

import os
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

from cv_masking.adapters.clock import SystemClock
from cv_masking.adapters.detection import PatternDetector
from cv_masking.adapters.docx import DocxExtractor, DocxVerifier, DocxXmlRedactor
from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor, PyMuPDFVerifier
from cv_masking.application import (
    DetectionService,
    DocumentPipeline,
    RedactionService,
    VerificationService,
)
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory, HiddenContentCounts
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.detection import DetectionResult
from cv_masking.ports.extraction import ExtractedDocument
from cv_masking.ports.processing import ProcessingReport, ValidationReport, VerificationReport
from cv_masking.ports.storage import StoredObject

LIGHT: Final = b"%PDF-stub light\n"
MALFORMED: Final = b"%PDF-stub malformed\n"
BLOCKED: Final = b"%PDF-stub blocked\n"
HIDDEN: Final = b"%PDF-stub hidden\n"
REVIEW: Final = b"%PDF-stub review\n"
HANG: Final = b"%PDF-stub hang\n"
CRASH: Final = b"%PDF-stub crash\n"
BUSY: Final = b"%PDF-stub busy\n"

STUB_VERIFIER_ID: Final = "stub-verifier"
STUB_VERIFIER_VERSION: Final = "1.0.0"
BUSY_SECONDS: Final = 1.5


def stub_output(data: bytes) -> bytes:
    """The deterministic 'redacted' output for an input."""
    return b"%PDF-stub output " + sha256(data).hexdigest().encode() + b"\n"


class StubPipeline:
    def __init__(self, root: Path) -> None:
        storage = StorageRoot.prepare(root)
        self._inputs = LocalInputStore(storage)
        self._outputs = LocalOutputStore(storage)
        self._data: bytes | None = None
        self._source: StoredObject | None = None

    def validate(self, source: StoredObject) -> ValidationReport:
        self.forget()
        self._inputs.verify(source)
        with self._inputs.open(source.ref, source.document_format) as handle:
            data = handle.read()
        marker = data.split(b"\n", 1)[0] + b"\n"
        if marker == MALFORMED:
            return ValidationReport(failure=ErrorCode.PDF_MALFORMED)
        if marker == BLOCKED:
            return ValidationReport(review=frozenset({ReviewReason.PDF_ENCRYPTED}))
        self._data, self._source = data, source
        if marker == HIDDEN:
            counts = ((HiddenContentCategory.ANNOTATIONS, 2),)
            return ValidationReport(hidden_removed=HiddenContentCounts(counts))
        return ValidationReport()

    def process(self, policy: MaskingPolicy) -> ProcessingReport:
        data = self._data
        assert data is not None
        if data.startswith(HANG):
            time.sleep(3600)
        if data.startswith(CRASH):
            os._exit(3)
        if data.startswith(BUSY):
            end = time.monotonic() + BUSY_SECONDS
            while time.monotonic() < end:
                sha256(data * 1000).digest()
        review = {ReviewReason.DETECT_LOW_CONFIDENCE} if data.startswith(REVIEW) else set()
        return ProcessingReport(
            output=stub_output(data),
            finding_counts=FindingCounts(((EntityType.CANDIDATE_NAME, 1),)),
            review=frozenset(review),
        )

    def verify(self, output: StoredObject) -> VerificationReport:
        self._outputs.verify(output)
        self.forget()
        return VerificationReport(
            result=VerificationResult(
                outcome=VerificationOutcome.PASSED,
                failure_codes=frozenset(),
                output_ref=output.ref,
                verifier_id=STUB_VERIFIER_ID,
                verifier_version=STUB_VERIFIER_VERSION,
                verified_at=datetime.now(UTC),
            )
        )

    def forget(self) -> None:
        self._data = None
        self._source = None


def stub_pipeline(root: Path) -> StubPipeline:
    return StubPipeline(root)


def failing_factory(root: Path) -> StubPipeline:
    raise RuntimeError("synthetic start failure")


class _NeverReturningDetector:
    def detect(self, document: ExtractedDocument) -> DetectionResult:
        while True:
            time.sleep(60)


def hanging_detector_pipeline(root: Path) -> DocumentPipeline:
    """The production composition with a detector that never returns."""
    storage = StorageRoot.prepare(root)
    inputs = LocalInputStore(storage)
    verification = VerificationService(
        inputs,
        LocalOutputStore(storage),
        PatternDetector(),
        SystemClock(),
        pdf=PyMuPDFVerifier(),
        docx=DocxVerifier(),
    )
    return DocumentPipeline(
        inputs,
        {DocumentFormat.PDF: PyMuPDFExtractor(), DocumentFormat.DOCX: DocxExtractor()},
        DetectionService(_NeverReturningDetector()),
        RedactionService(inputs, pdf=PyMuPDFRedactor(), docx=DocxXmlRedactor()),
        verification,
    )
