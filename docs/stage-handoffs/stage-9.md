# Stage 9 handoff — Span-to-box mapping

## Stage and objective

Stage 9 converts each PDF finding's character range into source word boxes on
its page, and groups overlapping findings into redaction regions for Stage 10.
No PDF is modified. DOCX findings keep their part and character range (Stage 0
note); Stage 10b consumes those.

## Architecture decisions

- **`application/mapping.py`** is pure geometry on the port types. It uses
  offsets and boxes only, holds no text, and has no I/O. `map_span(part, start,
  end)` returns `SpanMapping(boxes, ambiguous, partial_words)`, or None when the
  range cannot be placed.
- **Word-level mapping.** A finding takes every extracted word that overlaps
  its range.
  - **Partial words:** a word only partly inside the range is redacted whole.
    Examples are "Mẫu," with a trailing comma, or "Email:mau@…" where the label
    is glued to the value. This over-redacts instead of guessing sub-word
    geometry.
  - **Split tokens:** a token drawn as several fragments maps to all fragments
    and merges into one box.
- **Line boxes.** Consecutive words merge into one box when three conditions
  hold:
  - they share a line (vertical overlap ≥ 50% of the shorter box);
  - the gap between them is at most one line height;
  - no unrelated word on that line lies inside the merged box.

  Otherwise the words stay separate boxes, which covers wrapped lines, table
  cells, column gaps, and interleaved reading order. The 50% rule matters
  because PyMuPDF boxes on tightly spaced lines overlap vertically by about
  3.5 pt. Neighbouring lines must not count as the same line.
- **Failure and review** (the approved Stage 8 decision):
  - `MAP_FAILED`: any visible character of a finding has no source word box.
    `DetectionService` returns a failure with no findings, so the document
    fails.
  - `MAP_AMBIGUOUS`: a finding's word overlaps another word by at least 50% of
    the smaller box's area (text drawn twice or overprinted). Both boxes are
    redacted and the document goes to review.
- **`RedactionRegion`** is a new domain value object with `page_number`,
  `boxes`, `entity_type` and `finding_ids`, plus a `replacement_label`
  property. Findings join a region when any of their boxes overlap on the same
  line. The label is the winning type from `LABEL_PRIORITY`, which moved from
  the detection adapter to `domain/policy.py` with `label_winner()`. Region
  boxes that overlap on a line are unioned. Boxes on different lines are never
  unioned, so a region cannot cover unrelated words.
- **Long findings** with more than `MAX_BOXES_PER_FINDING` (64) boxes, such as
  a long family block, split into several findings of the same type.
- **`DetectionOutcome.regions`** carries the regions. The log line gains
  `ambiguous=` and `regions=` counts.
- **Debug view.** `tests/application/mapping_debug.py` lists, for each region
  box, the synthetic words whose box centre lies inside it, with the box
  coordinates. It lives in the test tree on purpose: runtime code never renders
  document text.

## Stage 8 fix found by the end-to-end tests

The PDF extractor reads table cells on one row as one line, for example a
referee's name cell followed by an email cell. The Stage 8 referee rules
rejected any line segment containing a colon, so that referee was missed.
Inside a references section the segment is now cut before an inline `label:`,
and the name is found. Labelled lines are still handled by the label rule
first. The header rule is unchanged: it still rejects colons, to avoid the "HỌ
VÀ TÊN:" false positive.

## Files added/changed

Added:
- `backend/src/cv_masking/application/mapping.py`
- `backend/tests/application/{synthetic_mapping,mapping_debug,test_mapping,test_mapping_pdf}.py`
- `docs/stage-handoffs/stage-9.md`

Changed:
- `backend/src/cv_masking/domain/findings.py`: `RedactionRegion`, `MAX_BOXES_PER_REGION`
- `backend/src/cv_masking/domain/policy.py`: `LABEL_PRIORITY`, `label_winner`
- `backend/src/cv_masking/application/detection.py`: mapping, `MAP_FAILED`/`MAP_AMBIGUOUS`, chunking, regions
- `backend/src/cv_masking/adapters/detection/hits.py`: uses the domain priority table
- `backend/src/cv_masking/adapters/detection/names.py`: referee segment cut at inline labels
- `backend/tests/application/test_names.py`: no-box PDF match now fails with `MAP_FAILED`
- `backend/tests/domain/{test_no_pii_fields,test_policy}.py`: region field allowlist; priority table covers every type
- Docs: `README.md`, `docs/stage-plan.md`, `docs/error-codes.md` (`MAP_*` meanings), `docs/masking-policy.md` §5

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `147 file(s) checked, none refused.` |
| `ruff check src tests` | `All checks passed!` |
| `mypy src tests` (strict) | `Success: no issues found in 106 source files` |
| `python scripts/run_pytest.py` | `298 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

Thirty-five new backend tests (263 → 298).

`test_mapping.py` uses hand-built pages with exact word boxes, and a fixed
detector so that placement is tested on its own:
- **Basic placement:**
  - a single word maps to its own box;
  - words on one line merge without their neighbours;
  - a wrapped line gives one box per line.
- **Word boundaries:**
  - trailing punctuation and glued labels redact the whole word;
  - split-token fragments merge into one box.
- **Layout:**
  - table cells are not bridged;
  - a column gap splits boxes;
  - a merge is refused when an unrelated word sits in between;
  - overlap between neighbouring lines is not ambiguous.
- **Duplicates:** an overprinted word sets `MAP_AMBIGUOUS` and redacts both
  boxes. Duplicate occurrences map to their own boxes and regions.
- **Failures:**
  - an uncovered visible character gives `MAP_FAILED` with no findings;
  - whitespace between words needs no box;
  - out-of-range spans fail.
- **Chunking:** long findings split at 64 boxes.
- **Regions:**
  - the same word as `PHONE` and `NATIONAL_ID` gives one region labelled
    `[ID]`;
  - a partial `EMAIL`/`PERSONAL_URL` overlap gives one unioned box;
  - findings on neighbouring lines stay separate;
  - DOCX findings get no regions;
  - regions never cross pages.
- **Domain:** `label_winner` cases and `RedactionRegion` invariants.

`test_mapping_pdf.py` runs synthetic PDF bytes through `PyMuPDFExtractor`, then
`PresidioDetector` and `DetectionService`. The PDF has:
- a large-font title with an NFD-decomposed Vietnamese name;
- a glued `Email:` contact line with a phone number;
- a table row;
- a wrapped referee cell;
- a second page repeating the email.

The tests check that:
- each region covers exactly its entity's words;
- the title is found by `largest_font` without review, which closes the Stage 8
  gap;
- no company, job-title, heading, label or separator word is covered;
- regions sit on their findings' pages;
- the debug view has words and valid coordinates for every box;
- logs, findings and regions contain no fixture values.

## Security/privacy review

- **No new dependency, subprocess, network, or file I/O.** Mapping is in-memory
  geometry. PyMuPDF is used only in tests to build synthetic PDFs, as before.
- **No text in outputs.** `SpanMapping` and `RedactionRegion` hold offsets,
  coordinates, types and IDs only. The domain field allowlist now includes
  `RedactionRegion`, and it has no string fields. Logs are counts.
- **Debug view is test-only.** It never ships in `src/`, and tests assert
  booleans and counts, so failures don't print fixture text.
- **Fail-closed.**
  - Unplaceable findings fail the document.
  - Overprinted words over-redact and go to review.
  - Partial words over-redact.
- **The agent never read, listed, or searched `data/`.** All fixtures are
  generated at test time; no PDF bytes are committed.

## Known limitations

- **No sub-word precision.** Glued labels such as "Email:" are redacted with
  their value. Precise cuts would need per-character boxes from PyMuPDF
  `rawdict` in the Stage 6 extractor.
- **Box overlap between lines.** PyMuPDF word boxes on tightly spaced lines
  overlap vertically by about 3.5 pt. Mapping handles this, but Stage 10 must
  check that `apply_redactions` does not remove glyphs from the neighbouring
  line. That may mean trimming rects vertically or choosing the text-removal
  option.
- **Rotated or vertical text** gets one box per word, because those words are
  not on a shared horizontal line. Correct, but not merged.
- **Hyphenated words across a line break** (for example "Nguy-" / "ễn") are
  not joined, so detection does not see the name. That is a detection limit;
  mapping would place it.
- **Not wired into the worker** (Stage 12). Stage 10 consumes
  `DetectionOutcome.regions`.

## Manual verification steps

1. `make check` passes.
2. To inspect geometry on synthetic data, call `render(debug_rows(document,
   outcome.regions))` from `tests/application/mapping_debug.py` in a local
   session. Do this only with fixtures from `synthetic_mapping.py`, never with
   a real CV.

## Questions/decisions for the tech lead

Resolved after review:

1. **`MAP_FAILED` is now non-retryable (`T`).** Mapping is pure and
   deterministic, so neither cause can succeed on re-upload. Removed from
   `RETRYABLE_ERROR_CODES`; `docs/error-codes.md` updated.
2. **Whole-word over-redaction is accepted for the PoC** (D-28 in
   `docs/product-scope.md`). Revisit only if Stage 16 evaluation shows it harms
   usability.
3. **Counts are one per detected entity.** `DetectionOutcome.counts` counts
   matches, so a long match split into several findings counts once.
4. **Stage 10 acceptance test** for tight line spacing is recorded in
   `docs/stage-plan.md` under Stage 10.

## Suggested commit message

```text
feat(map): map PDF findings to word boxes and merge overlaps into regions (Stage 9)

- Line-aware box merging that never covers unrelated words; partial words redact whole
- MAP_FAILED for unplaceable findings, MAP_AMBIGUOUS for overprinted words
```
