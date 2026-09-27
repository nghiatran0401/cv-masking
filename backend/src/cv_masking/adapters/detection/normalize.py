"""NFC-safe folding for label matching. Offsets always map back to the original text."""

import unicodedata


def fold_with_map(text: str) -> tuple[str, list[int], list[int | None]]:
    """Return folded text, folded→original indexes, and original→first folded index."""
    folded: list[str] = []
    mapping: list[int] = []
    orig_to_fold: list[int | None] = [None] * len(text)
    for index, char in enumerate(text):
        stripped = "".join(
            mark
            for mark in unicodedata.normalize("NFD", char)
            if unicodedata.category(mark) != "Mn"
        )
        first = True
        for piece in stripped.casefold():
            if first:
                orig_to_fold[index] = len(folded)
                first = False
            folded.append(piece)
            mapping.append(index)
    return "".join(folded), mapping, orig_to_fold


def original_span(mapping: list[int], folded_start: int, folded_end: int) -> tuple[int, int]:
    if folded_end <= folded_start or folded_start >= len(mapping):
        return (0, 0)
    end_index = min(folded_end, len(mapping)) - 1
    return mapping[folded_start], mapping[end_index] + 1
