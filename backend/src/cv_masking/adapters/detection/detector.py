"""Presidio pattern recognizers plus labeled-field rules. No spaCy models, no network."""

import re
from typing import Final

from presidio_analyzer import Pattern, PatternRecognizer

from cv_masking.adapters.detection.context import contact_address_hits, family_hits
from cv_masking.adapters.detection.hits import Hit, resolve
from cv_masking.adapters.detection.names import (
    NameAnchor,
    email_tokens,
    header_candidate,
    label_names,
    reference_line_names,
    repeat_hits,
)
from cv_masking.adapters.detection.normalize import fold_with_map, original_span
from cv_masking.adapters.detection.sections import PartView, SectionKind, build_view
from cv_masking.domain.catalogue import (
    AGE_AFTER_LABEL_RE,
    AGE_BEFORE_LABEL_RE,
    ANYWHERE_PATTERNS,
    CONTACT_LABELS,
    CONTEXT_PATTERNS,
    CONTEXT_WINDOW,
    DATE_RE,
    DETECTOR_VERSION,
    DOB_AGE_RE,
    EXTRA_STOP_LABELS,
    FIELD_LABELS,
    LABELED_VALUE_KIND,
    SALARY_LABELS,
    SALARY_RE,
    SCORE_HIGH,
    SCORE_VALUE,
    YEAR_RE,
)
from cv_masking.domain.policy import REPLACEMENT_LABELS, EntityType
from cv_masking.ports.detection import DetectionResult, TextMatch
from cv_masking.ports.extraction import ExtractedDocument, TextPart

_REPLACEMENTS: Final = tuple(sorted(set(REPLACEMENT_LABELS.values()), key=len, reverse=True))
_VALUE_STOP_LABELS: Final = tuple(
    dict.fromkeys(
        (
            *(label for _, labels in FIELD_LABELS for label in labels),
            *CONTACT_LABELS,
            *EXTRA_STOP_LABELS,
        )
    )
)


class PresidioDetector:
    """Presidio PatternRecognizer rules plus explainable name/section heuristics.

    No NLP engine, no model files, no network.
    """

    def __init__(self) -> None:
        self._patterns = _recognizers()

    def detect(self, document: ExtractedDocument) -> DetectionResult:
        views = tuple(build_view(part) for part in document.parts)
        emails = email_tokens(views)
        per_part: list[list[Hit]] = [_field_hits(view.part, self._patterns) for view in views]
        anchors: list[NameAnchor] = []
        for index, view in enumerate(views):
            labeled, references = label_names(view, index)
            anchors.extend(labeled)
            per_part[index].extend(references)
            per_part[index].extend(reference_line_names(view))
            per_part[index].extend(family_hits(view))
            if view.is_contact_part:
                per_part[index].extend(contact_address_hits(view))
        header = _best_header(views, emails, anchors)
        if header is not None:
            anchors.append(header)
        for anchor in anchors:
            per_part[anchor.part_index].append(anchor.hit())
        matches: list[TextMatch] = []
        for index, view in enumerate(views):
            per_part[index].extend(repeat_hits(view, index, anchors))
            refs = view.ranges(SectionKind.REFERENCE)
            matches.extend(_to_match(hit, view.part, refs) for hit in resolve(per_part[index]))
        return DetectionResult(tuple(matches))


class PatternDetector:
    """Only the deterministic Stage 7 rules: value shapes and labeled fields.

    The Stage 8 name and section heuristics are left out on purpose. They depend
    on layout context, and a redacted page changes that context (the line after
    a redacted name becomes the "first line"), so on an output they would flag
    unrelated text. The verifier catches names by searching for source values.
    """

    def __init__(self) -> None:
        self._patterns = _recognizers()

    def detect(self, document: ExtractedDocument) -> DetectionResult:
        matches: list[TextMatch] = []
        for part in document.parts:
            hits = resolve(_field_hits(part, self._patterns))
            matches.extend(_to_match(hit, part, ()) for hit in hits)
        return DetectionResult(tuple(matches))


def _recognizers() -> tuple[PatternRecognizer, ...]:
    return tuple(
        PatternRecognizer(
            supported_entity=pattern.entity,
            name=pattern.entity,
            patterns=[Pattern(pattern.name, pattern.regex, pattern.score)],
            version=DETECTOR_VERSION,
        )
        for pattern in ANYWHERE_PATTERNS
    )


def _best_header(
    views: tuple[PartView, ...], emails: frozenset[str], anchors: list[NameAnchor]
) -> NameAnchor | None:
    labeled = {anchor.folded_tokens for anchor in anchors}
    best: NameAnchor | None = None
    for index, view in enumerate(views):
        if not view.is_contact_part:
            continue
        candidate = header_candidate(view, index, emails)
        if candidate is None or candidate.folded_tokens in labeled:
            continue
        if best is None or candidate.confidence > best.confidence:
            best = candidate
    return best


def _field_hits(part: TextPart, patterns: tuple[PatternRecognizer, ...]) -> list[Hit]:
    text = part.text
    if not text:
        return []
    folded, mapping, orig_to_fold = fold_with_map(text)
    hits = _pattern_hits(text, patterns)
    hits.extend(_context_digits(text, folded, mapping, orig_to_fold))
    hits.extend(_labeled_fields(text, folded, mapping))
    hits.extend(_age_hits(text))
    hits.extend(_salary_hits(text, folded, mapping, orig_to_fold))
    return hits


def _pattern_hits(text: str, patterns: tuple[PatternRecognizer, ...]) -> list[Hit]:
    hits: list[Hit] = []
    for recognizer in patterns:
        entity = EntityType(recognizer.get_supported_entities()[0])
        for result in recognizer.analyze(text, entities=[entity.value], regex_flags=0):
            if result.start is None or result.end is None:
                continue
            hits.append(Hit(entity, result.start, result.end, float(result.score), entity.value))
    return hits


def _context_digits(
    text: str,
    folded: str,
    mapping: list[int],
    orig_to_fold: list[int | None],
) -> list[Hit]:
    hits: list[Hit] = []
    for pattern in CONTEXT_PATTERNS:
        entity = EntityType(pattern.entity)
        for match in re.finditer(pattern.regex, text):
            if _has_label_before(folded, mapping, orig_to_fold, match.start(), pattern.labels):
                hits.append(Hit(entity, match.start(), match.end(), pattern.score, entity.value))
    return hits


def _labeled_fields(text: str, folded: str, mapping: list[int]) -> list[Hit]:
    hits: list[Hit] = []
    for entity_name, labels in FIELD_LABELS:
        entity = EntityType(entity_name)
        for label in labels:
            for match in re.finditer(_label_re(label), folded):
                start, label_end = original_span(mapping, match.start(), match.end())
                if label_end <= start:
                    continue
                value_start = _skip_sep(text, label_end)
                value_end = _value_end(text, value_start)
                if value_end <= value_start:
                    continue
                kind = LABELED_VALUE_KIND.get(entity_name)
                if kind == "dob":
                    hits.extend(_dob_from_value(text, value_start, value_end, folded, mapping))
                    continue
                if kind == "salary":
                    hits.extend(_salary_in(text, value_start, value_end, folded, mapping))
                    continue
                if kind == "skip":
                    continue
                hits.append(Hit(entity, value_start, value_end, SCORE_HIGH, entity.value))
    return hits


def _dob_from_value(text: str, start: int, end: int, folded: str, mapping: list[int]) -> list[Hit]:
    slice_text = text[start:end]
    fold_start = _fold_index(mapping, start)
    folded_slice = folded[fold_start : _fold_index(mapping, end)]
    dates = _dob_pattern_hits(folded_slice, fold_start, mapping, DATE_RE)
    if dates:
        return dates
    ages = _dob_pattern_hits(folded_slice, fold_start, mapping, DOB_AGE_RE)
    if ages:
        return ages
    if any(label in slice_text for label in _REPLACEMENTS):
        return []
    year = re.search(YEAR_RE, folded_slice)
    if year is not None and folded_slice[: year.start()].strip() == "":
        orig_start, orig_end = original_span(
            mapping, fold_start + year.start(), fold_start + year.end()
        )
        if orig_end > orig_start:
            return [
                Hit(EntityType.DATE_OF_BIRTH, orig_start, orig_end, SCORE_VALUE, "date_of_birth")
            ]
        return []
    if slice_text.strip():
        return [Hit(EntityType.DATE_OF_BIRTH, start, end, SCORE_VALUE, "date_of_birth")]
    return []


def _dob_pattern_hits(
    folded_slice: str, fold_start: int, mapping: list[int], pattern: str
) -> list[Hit]:
    found: list[Hit] = []
    for match in re.finditer(pattern, folded_slice, flags=re.IGNORECASE):
        orig_start, orig_end = original_span(
            mapping, fold_start + match.start(), fold_start + match.end()
        )
        if orig_end > orig_start:
            found.append(
                Hit(EntityType.DATE_OF_BIRTH, orig_start, orig_end, SCORE_VALUE, "date_of_birth")
            )
    return found


def _label_re(label: str) -> str:
    """A field label as a whole word, never a prefix of ``agent`` / ``[DOB]``."""
    return rf"(?<![\w\[]){re.escape(label)}(?!\w)\s*[:\-]?"


def _age_hits(text: str) -> list[Hit]:
    hits: list[Hit] = []
    for pattern in (AGE_AFTER_LABEL_RE, AGE_BEFORE_LABEL_RE):
        for match in re.finditer(pattern, text):
            hits.append(
                Hit(
                    EntityType.DATE_OF_BIRTH,
                    match.start(1),
                    match.end(1),
                    SCORE_VALUE,
                    "date_of_birth",
                )
            )
    return hits


def _salary_hits(
    text: str, folded: str, mapping: list[int], orig_to_fold: list[int | None]
) -> list[Hit]:
    return _salary_in(
        text, 0, len(text), folded, mapping, require_label=True, orig_to_fold=orig_to_fold
    )


def _salary_in(
    text: str,
    start: int,
    end: int,
    folded: str,
    mapping: list[int],
    *,
    require_label: bool = False,
    orig_to_fold: list[int | None] | None = None,
) -> list[Hit]:
    hits: list[Hit] = []
    region = text[start:end]
    for match in re.finditer(SALARY_RE, region, flags=re.IGNORECASE):
        abs_start, abs_end = start + match.start(), start + match.end()
        if (
            require_label
            and orig_to_fold is not None
            and not _has_label_before(folded, mapping, orig_to_fold, abs_start, SALARY_LABELS)
        ):
            continue
        hits.append(Hit(EntityType.SALARY, abs_start, abs_end, SCORE_VALUE, "salary"))
    return hits


def _has_label_before(
    folded: str,
    mapping: list[int],
    orig_to_fold: list[int | None],
    orig_start: int,
    labels: tuple[str, ...],
) -> bool:
    fold_at = orig_to_fold[orig_start] if orig_start < len(orig_to_fold) else None
    if fold_at is None:
        fold_at = _fold_index(mapping, orig_start)
    window = folded[max(0, fold_at - CONTEXT_WINDOW) : fold_at]
    return any(re.search(rf"(?<!\w){re.escape(label)}(?!\w)", window) for label in labels)


def _skip_sep(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t:-":
        index += 1
    return index


def _value_end(text: str, start: int) -> int:
    newline = text.find("\n", start)
    end = len(text) if newline < 0 else newline
    raw = text[start:end]
    if not raw.strip():
        return start
    for label in _REPLACEMENTS:
        if raw.startswith(label):
            return start + len(label)
        idx = raw.find(label)
        if idx > 0:
            end = min(end, start + idx)
            raw = text[start:end]
    pipe = raw.find("|")
    if pipe >= 0:
        end = start + pipe
        raw = text[start:end]
    folded_val, val_map, _ = fold_with_map(raw)
    cut: int | None = None
    for label in _VALUE_STOP_LABELS:
        found = re.search(rf"(?:^|\s)({re.escape(label)})\s*[:\-]", folded_val)
        if found is not None and found.start() > 0:
            at = val_map[found.start()]
            cut = at if cut is None else min(cut, at)
    if cut is not None:
        end = start + cut
    return _rtrim(text, start, end)


def _rtrim(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1] in " \t,;":
        end -= 1
    return end


def _fold_index(mapping: list[int], orig: int) -> int:
    for folded_i, original_i in enumerate(mapping):
        if original_i >= orig:
            return folded_i
    return len(mapping)


def _to_match(hit: Hit, part: TextPart, refs: tuple[tuple[int, int], ...]) -> TextMatch:
    detector_id = hit.detector_id
    signals = hit.signals
    if hit.entity_type in {EntityType.EMAIL, EntityType.PHONE} and any(
        start <= hit.start < end for start, end in refs
    ):
        detector_id = f"{hit.entity_type.value}.reference"
        signals = (*signals, "reference_section")
    return TextMatch(
        entity_type=hit.entity_type,
        start=hit.start,
        end=hit.end,
        confidence=hit.confidence,
        detector_id=detector_id,
        detector_version=DETECTOR_VERSION,
        page_number=part.page_number,
        part_name=part.part_name,
        signals=signals,
    )
