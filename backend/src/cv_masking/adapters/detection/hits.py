"""Internal detector hits and overlap resolution. Hits never carry text."""

from dataclasses import dataclass

from cv_masking.domain.policy import EntityType

_PRIORITY = {
    EntityType.EMAIL: 100,
    EntityType.NATIONAL_ID: 90,
    EntityType.PASSPORT: 85,
    EntityType.DATE_OF_BIRTH: 80,
    EntityType.SALARY: 80,
    EntityType.POSTAL_ADDRESS: 75,
    EntityType.PHONE: 70,
    EntityType.CANDIDATE_NAME: 65,
    EntityType.REFERENCE_NAME: 64,
    EntityType.PERSONAL_URL: 60,
    EntityType.FAMILY_DETAILS: 55,
    EntityType.GENDER: 50,
    EntityType.MARITAL_STATUS: 50,
    EntityType.NATIONALITY: 50,
    EntityType.RELIGION: 50,
    EntityType.ETHNICITY: 50,
    EntityType.HEALTH: 50,
}


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
        merged, key=lambda hit: (-(hit.end - hit.start), -_PRIORITY.get(hit.entity_type, 10))
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
