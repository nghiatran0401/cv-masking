"""Internal detector hits and overlap resolution. Hits never carry text."""

from dataclasses import dataclass

from cv_masking.domain.policy import LABEL_PRIORITY, EntityType


@dataclass(frozen=True, slots=True)
class Hit:
    entity_type: EntityType
    start: int
    end: int
    confidence: float
    detector_id: str
    signals: tuple[str, ...] = ()


def resolve(hits: list[Hit]) -> list[Hit]:
    """Merge same-type overlaps; drop a hit only when another type fully covers it.

    Partial overlaps of different types are both kept so no characters lose
    coverage; the redactor redacts the union.
    """
    merged = _merge_same_type(hits)
    ordered = sorted(
        merged, key=lambda hit: (-(hit.end - hit.start), -LABEL_PRIORITY[hit.entity_type])
    )
    kept: list[Hit] = []
    for hit in ordered:
        if any(
            other.entity_type is not hit.entity_type
            and other.start <= hit.start
            and hit.end <= other.end
            for other in kept
        ):
            continue
        kept.append(hit)
    return sorted(kept, key=lambda hit: (hit.start, hit.end, hit.entity_type.value))


def _merge_same_type(hits: list[Hit]) -> list[Hit]:
    by_type: dict[EntityType, list[Hit]] = {}
    for hit in hits:
        by_type.setdefault(hit.entity_type, []).append(hit)
    merged: list[Hit] = []
    for group in by_type.values():
        group.sort(key=lambda hit: (hit.start, hit.end))
        current = group[0]
        for hit in group[1:]:
            if hit.start < current.end:
                current = _union(current, hit)
            else:
                merged.append(current)
                current = hit
        merged.append(current)
    return merged


def _union(left: Hit, right: Hit) -> Hit:
    stronger = left if left.confidence >= right.confidence else right
    signals = tuple(dict.fromkeys((*left.signals, *right.signals)))
    return Hit(
        left.entity_type,
        min(left.start, right.start),
        max(left.end, right.end),
        max(left.confidence, right.confidence),
        stronger.detector_id,
        signals,
    )
