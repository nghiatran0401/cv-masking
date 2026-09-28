"""In-process evaluation: extract, detect, redact. No SQLite and no data/ writes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.docx import DocxExtractor, DocxXmlRedactor
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor
from cv_masking.application import DetectionService
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import POLICY_VERSION, EntityType, MaskingPolicy
from cv_masking.evaluation.fixtures import (
    annotated_docx,
    annotated_pdf,
    magic_format,
    malformed_docx,
    malformed_pdf,
)
from cv_masking.evaluation.metrics import EntityScores, gold_spans, leak_count, score_entities
from cv_masking.ports.extraction import DocumentExtractor

AUTHORIZED_ENV = "CV_MASKING_AUTHORIZED_EVAL"
MAX_AUTHORIZED_BYTES = 21 * 1024 * 1024


@dataclass
class FormatTotals:
    documents: int = 0
    scored: int = 0
    failed: int = 0
    review_required: int = 0
    leaked_distinctive: int = 0
    duration_ms: int = 0
    entities: dict[EntityType, EntityScores] = field(default_factory=dict)


@dataclass
class EvalReport:
    set_name: str
    policy_version: str
    photos_and_images_unmasked: bool
    by_format: dict[DocumentFormat, FormatTotals]


def _merge_scores(
    left: dict[EntityType, EntityScores], right: dict[EntityType, EntityScores]
) -> dict[EntityType, EntityScores]:
    merged: dict[EntityType, EntityScores] = dict(left)
    for entity, extra in right.items():
        current = merged.get(entity)
        if current is None:
            merged[entity] = extra
            continue
        merged[entity] = EntityScores(
            gold=current.gold + extra.gold,
            predicted=current.predicted + extra.predicted,
            true_positive=current.true_positive + extra.true_positive,
            false_positive=current.false_positive + extra.false_positive,
            false_negative=current.false_negative + extra.false_negative,
        )
    return merged


class _Engine:
    def __init__(self) -> None:
        self.detection = DetectionService(PresidioDetector())
        self.extractors: dict[DocumentFormat, DocumentExtractor] = {
            DocumentFormat.PDF: PyMuPDFExtractor(),
            DocumentFormat.DOCX: DocxExtractor(),
        }
        self.pdf_redactor = PyMuPDFRedactor()
        self.docx_redactor = DocxXmlRedactor()
        self.policy = MaskingPolicy()


def _status_and_scores(
    engine: _Engine, data: bytes, fmt: DocumentFormat
) -> tuple[str, int, dict[EntityType, EntityScores]]:
    extracted = engine.extractors[fmt].extract(data)
    if extracted.failure is not None:
        return "failed", 0, {}
    if extracted.review:
        return "review_required", 0, {}
    document = extracted.document
    if document is None:
        return "failed", 0, {}
    detection = engine.detection.detect(document, engine.policy)
    if detection.failure is not None:
        return "failed", 0, {}
    status = "review_required" if detection.review else "ok"
    scores = score_entities(gold_spans(document), detection.matches)
    if fmt is DocumentFormat.PDF:
        redacted = engine.pdf_redactor.redact(data, detection.regions)
    else:
        redacted = engine.docx_redactor.redact(data, detection.docx_ranges)
    if redacted.failure is not None or redacted.output is None:
        return "failed", 0, scores
    return status, leak_count(redacted.output), scores


def _accumulate(
    bucket: FormatTotals,
    status: str,
    leaks: int,
    scores: dict[EntityType, EntityScores],
    elapsed_ms: int,
) -> None:
    bucket.documents += 1
    bucket.duration_ms += elapsed_ms
    if status == "failed":
        bucket.failed += 1
        return
    if status == "review_required":
        bucket.review_required += 1
        if not scores:
            return
    bucket.scored += 1
    bucket.leaked_distinctive += leaks
    bucket.entities = _merge_scores(bucket.entities, scores)


def run_synthetic() -> EvalReport:
    engine = _Engine()
    totals: dict[DocumentFormat, FormatTotals] = {
        DocumentFormat.PDF: FormatTotals(),
        DocumentFormat.DOCX: FormatTotals(),
    }
    cases: tuple[tuple[DocumentFormat, bytes], ...] = (
        (DocumentFormat.PDF, annotated_pdf()),
        (DocumentFormat.PDF, malformed_pdf()),
        (DocumentFormat.DOCX, annotated_docx()),
        (DocumentFormat.DOCX, malformed_docx()),
    )
    for fmt, data in cases:
        started = perf_counter()
        status, leaks, scores = _status_and_scores(engine, data, fmt)
        _accumulate(
            totals[fmt],
            status,
            leaks,
            scores,
            int((perf_counter() - started) * 1000),
        )
    return EvalReport(
        set_name="synthetic",
        policy_version=POLICY_VERSION,
        photos_and_images_unmasked=True,
        by_format=totals,
    )


def run_authorized(directory: Path) -> EvalReport:
    """Operational metrics only. Never records names, paths, or values (D-40)."""
    if os.environ.get(AUTHORIZED_ENV) != "1":
        raise PermissionError(
            "authorized evaluation is refused unless CV_MASKING_AUTHORIZED_EVAL=1"
        )
    if not directory.is_dir() or directory.is_symlink():
        raise FileNotFoundError("authorized directory missing")
    engine = _Engine()
    totals: dict[DocumentFormat, FormatTotals] = {
        DocumentFormat.PDF: FormatTotals(),
        DocumentFormat.DOCX: FormatTotals(),
    }
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        if size <= 0 or size > MAX_AUTHORIZED_BYTES:
            continue
        data = path.read_bytes()
        fmt = magic_format(data)
        if fmt is None:
            continue
        started = perf_counter()
        status, leaks, _scores = _status_and_scores(engine, data, fmt)
        _accumulate(
            totals[fmt],
            status,
            leaks,
            {},
            int((perf_counter() - started) * 1000),
        )
    return EvalReport(
        set_name="authorized",
        policy_version=POLICY_VERSION,
        photos_and_images_unmasked=True,
        by_format=totals,
    )
