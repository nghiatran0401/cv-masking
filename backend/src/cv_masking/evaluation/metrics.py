"""Precision, recall, and leak counts. Never stores values."""

from __future__ import annotations

from dataclasses import dataclass

from cv_masking.domain.policy import EntityType
from cv_masking.evaluation.fixtures import ANNOTATIONS
from cv_masking.ports.detection import TextMatch
from cv_masking.ports.extraction import ExtractedDocument

MIN_LEAK_CHARS = 6


@dataclass(frozen=True, slots=True)
class GoldSpan:
    entity_type: EntityType
    part_key: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class EntityScores:
    gold: int
    predicted: int
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float | None:
        if self.predicted == 0:
            return None
        return self.true_positive / self.predicted

    @property
    def recall(self) -> float | None:
        if self.gold == 0:
            return None
        return self.true_positive / self.gold


def part_key(page_number: int | None, part_name: str | None) -> str:
    if page_number is not None:
        return f"page:{page_number}"
    if part_name is not None:
        return f"part:{part_name}"
    return "unknown"


def _drop_contained(spans: tuple[GoldSpan, ...]) -> tuple[GoldSpan, ...]:
    """Ignore a short gold span that sits inside a longer annotated value (e.g. nationality)."""
    kept: list[GoldSpan] = []
    for span in spans:
        nested = any(
            other.part_key == span.part_key
            and (other.end - other.start) > (span.end - span.start)
            and other.start <= span.start
            and span.end <= other.end
            for other in spans
        )
        if not nested:
            kept.append(span)
    return tuple(kept)


def gold_spans(document: ExtractedDocument) -> tuple[GoldSpan, ...]:
    found: list[GoldSpan] = []
    for part in document.parts:
        key = part_key(part.page_number, part.part_name)
        text = part.text
        for entity, value in ANNOTATIONS:
            start = 0
            while True:
                index = text.find(value, start)
                if index < 0:
                    break
                found.append(GoldSpan(entity, key, index, index + len(value)))
                start = index + len(value)
    return _drop_contained(tuple(found))


def score_entities(
    gold: tuple[GoldSpan, ...], matches: tuple[TextMatch, ...]
) -> dict[EntityType, EntityScores]:
    gold_set = {(item.entity_type, item.part_key, item.start, item.end) for item in gold}
    pred_set = {
        (item.entity_type, part_key(item.page_number, item.part_name), item.start, item.end)
        for item in matches
    }
    types = {entity for entity, _, _, _ in gold_set | pred_set}
    scores: dict[EntityType, EntityScores] = {}
    for entity in types:
        gold_spans_e = {item[1:] for item in gold_set if item[0] is entity}
        pred_spans_e = {item[1:] for item in pred_set if item[0] is entity}
        true_pos = gold_spans_e & pred_spans_e
        scores[entity] = EntityScores(
            gold=len(gold_spans_e),
            predicted=len(pred_spans_e),
            true_positive=len(true_pos),
            false_positive=len(pred_spans_e - gold_spans_e),
            false_negative=len(gold_spans_e - pred_spans_e),
        )
    return scores


def leak_count(output: bytes) -> int:
    """How many distinctive annotated values remain in the output bytes."""
    leaked = 0
    seen: set[str] = set()
    decoded = output.decode("utf-8", errors="ignore")
    for _entity, value in ANNOTATIONS:
        if len(value) < MIN_LEAK_CHARS or value in seen:
            continue
        seen.add(value)
        if value.encode("utf-8") in output or value in decoded:
            leaked += 1
    return leaked
