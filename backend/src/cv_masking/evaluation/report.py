"""Serialize evaluation results as metadata-only JSON and Markdown."""

from __future__ import annotations

import json
from typing import Any

from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import EntityType
from cv_masking.evaluation.harness import EvalReport, FormatTotals
from cv_masking.evaluation.metrics import EntityScores


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _entity_json(scores: EntityScores) -> dict[str, Any]:
    precision = scores.precision
    recall = scores.recall
    return {
        "gold": scores.gold,
        "predicted": scores.predicted,
        "true_positive": scores.true_positive,
        "false_positive": scores.false_positive,
        "false_negative": scores.false_negative,
        "precision": None if precision is None else round(precision, 4),
        "recall": None if recall is None else round(recall, 4),
    }


def _format_json(fmt: DocumentFormat, bucket: FormatTotals) -> dict[str, Any]:
    entities = {
        entity.value: _entity_json(scores)
        for entity, scores in sorted(bucket.entities.items(), key=lambda item: item[0].value)
    }
    return {
        "format": fmt.value,
        "documents": bucket.documents,
        "scored": bucket.scored,
        "failed": bucket.failed,
        "review_required": bucket.review_required,
        "failure_rate": _rate(bucket.failed, bucket.documents),
        "review_required_rate": _rate(bucket.review_required, bucket.documents),
        "leaked_distinctive": bucket.leaked_distinctive,
        "duration_ms": bucket.duration_ms,
        "entities": entities,
    }


def report_dict(report: EvalReport) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "set": report.set_name,
        "policy_version": report.policy_version,
        "photos_and_images_unmasked": report.photos_and_images_unmasked,
        "by_format": [_format_json(fmt, report.by_format[fmt]) for fmt in DocumentFormat],
    }


def report_json(report: EvalReport) -> str:
    return json.dumps(report_dict(report), indent=2, sort_keys=True) + "\n"


def canonical_dict(report: EvalReport) -> dict[str, Any]:
    """Drop wall-clock times so two runs can be compared."""
    payload = report_dict(report)
    for item in payload["by_format"]:
        item.pop("duration_ms", None)
    return payload


def report_markdown(report: EvalReport) -> str:
    lines = [
        "# Evaluation report (metadata only)",
        "",
        f"Set: `{report.set_name}`. Policy version `{report.policy_version}`.",
        "",
        "Photos and embedded images are **not masked** (D-13).",
        "",
    ]
    for fmt in DocumentFormat:
        bucket = report.by_format[fmt]
        lines.extend(
            [
                f"## {fmt.value.upper()}",
                "",
                f"- documents: {bucket.documents}",
                f"- scored: {bucket.scored}",
                f"- failed: {bucket.failed} (rate {_rate(bucket.failed, bucket.documents)})",
                f"- review-required: {bucket.review_required} "
                f"(rate {_rate(bucket.review_required, bucket.documents)})",
                f"- leaked distinctive values: {bucket.leaked_distinctive}",
                f"- duration_ms: {bucket.duration_ms}",
                "",
                "| entity | gold | pred | tp | fp | fn | precision | recall |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for entity in EntityType:
            scores = bucket.entities.get(entity)
            if scores is None:
                continue
            header = "| {entity} | {gold} | {pred} | {tp} | {fp} | {fn} | {precision} | {recall} |"
            lines.append(
                header.format(
                    entity=entity.value,
                    gold=scores.gold,
                    pred=scores.predicted,
                    tp=scores.true_positive,
                    fp=scores.false_positive,
                    fn=scores.false_negative,
                    precision=scores.precision
                    if scores.precision is None
                    else round(scores.precision, 4),
                    recall=scores.recall if scores.recall is None else round(scores.recall, 4),
                )
            )
        lines.append("")
    return "\n".join(lines)
