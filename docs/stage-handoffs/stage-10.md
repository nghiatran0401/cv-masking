# Stage 10 handoff — Permanent PDF redaction

## Stage and objective

Stage 10 turns Stage 9 redaction regions into a new, permanently redacted PDF.
It uses PyMuPDF redaction annotations followed by `apply_redactions`, strips
the always-removed metadata, and removes each approved hidden-content category
(D-29). The input is never modified. The result is reopened and checked before
it is returned. It is not wired into jobs, the API, or the UI yet (Stage 12).

## Architecture decisions

- **Port `ports/redaction.py`.**
  - `DocumentRedactor.redact(data, regions, *, remove_hidden) -> RedactionResult`.
  - `RedactionResult` holds exactly one of new output bytes or an error code
    from `REDACT_FAILED`, `REDACT_SANITIZE_FAILED`, `REDACT_OUTPUT_WRITE_FAILED`,
    plus counts of labelled and solid regions.
- **`application/redaction.py` — `RedactionService`.**
  1. Verifies the stored input's hash, reads it, and runs the format's redactor.
  2. Saves the result as a new output object.
  3. Verifies the input hash again. If the input changed during redaction, the
     output is deleted and the storage code is returned.

  A failed detection or a format without a redactor is a programming error
  (`InvariantError`). The service logs counts only.
- **Regions follow the policy (`application/detection.py`).** Salary findings
  are always returned, but regions and the low-confidence review flag only
  cover the types the policy redacts. With the toggle OFF, salary text stays in
  the output.
- **`adapters/pdf/redactor.py` — `PyMuPDFRedactor`.**
  - **Refused inputs:** encrypted, outside 1–30 pages, too many objects, or a
    region on a missing page.
  - **Redaction:** one `add_redact_annot` per region box, then
    `apply_redactions(images=NONE, graphics=NONE, text=REMOVE)`. Images and
    line art are kept (D-13); every glyph a rectangle touches is removed.
  - **Trimming (Stage 9 decision).** Each rectangle is clipped vertically to
    stop 0.25 pt short of words on the lines above and below. A word counts as
    a neighbour when it overlaps horizontally and shares less than 50% of its
    height with the box. If nothing is left, the untrimmed box is used.
  - **Labels (Stage 8 decision).** One label per region, drawn in Helvetica
    inside the redaction annotation itself, at most 10 pt and only if it fits
    at ≥ 6 pt. It goes in the region box with the largest fitting size; other
    boxes and regions with no fit are solid black. Text is grey 0.9, because
    the hidden-content scan treats white text as invisible.
  - **Always stripped:** info dictionary and XMP metadata (including metadata
    on objects), outlines, page labels, thumbnails, link annotations, and an
    attachment-panel `PageMode`. The file is fully rewritten
    (`garbage=4, deflate=True`), so earlier revisions are gone.
  - **Approved hidden content** (`remove_hidden=True`; without approval any
    finding refuses with `REDACT_SANITIZE_FAILED`):
    - comment and markup annotations;
    - form widgets and `AcroForm`;
    - embedded files, portfolios, and the `EmbeddedFiles` name tree;
    - JavaScript: catalogue and page actions, the `JavaScript` name tree, and
      action objects emptied;
    - invisible text (render mode 3, zero opacity, white, sub-2 pt, or outside
      the crop box), removed with fill-less redaction annotations;
    - hidden optional-content layers (see below).
  - **Output self-check.** The output is reopened. It is refused if:
    - the page count differs or any redaction annotation is left
      (`REDACT_FAILED`);
    - any non-label word's centre lies inside an original region box
      (`REDACT_FAILED`);
    - the hidden-content scan finds anything, or a stripped catalogue entry is
      still present (`REDACT_SANITIZE_FAILED`).

    Because of this check, a no-op `apply_redactions` cannot produce an output.
- **Hidden layers: `adapters/pdf/content.py`.** A pure-bytes content-stream
  filter.
  - It tokenises strings (with nesting and escapes), hex strings, names,
    arrays, dictionaries, comments, and inline images.
  - Inside a hidden `/OC … BDC … EMC` block it removes text, shading, inline
    images, and `Do`. It turns path painting into `n` and keeps graphics and
    text state, so later content does not move.
  - Hidden form XObjects are handled two ways: they are filtered recursively,
    and a form under a hidden `/OC` is replaced with an empty form.
  - Anything unbalanced or unexpected raises `ContentError`, which gives
    `REDACT_SANITIZE_FAILED`.
  - Every page is rendered before and after filtering; any pixel difference
    refuses the output.
- **`adapters/pdf/hidden.py`.** The hidden-content scan moved out of the
  extractor so the redactor can re-scan its own output with the same rules.
  **Stage 6 bug fixed here:** PyMuPDF reports the text render mode under the
  key `type`, so render-mode-3 text was not flagged before. Zero-opacity text
  is now flagged too.

## Files added/changed

Added:
- `backend/src/cv_masking/ports/redaction.py`
- `backend/src/cv_masking/application/redaction.py`
- `backend/src/cv_masking/adapters/pdf/{hidden,content,redactor}.py`
- `backend/tests/application/{synthetic_redaction,test_redaction_pdf,test_redaction_hidden,test_pdf_content,test_redaction_service}.py`
- `backend/tests/architecture/test_redaction_boundaries.py`
- `docs/stage-handoffs/stage-10.md`

Changed:
- `backend/src/cv_masking/adapters/pdf/extractor.py`: uses `hidden.py`; `MAX_XREFS` made public
- `backend/src/cv_masking/adapters/pdf/__init__.py`, `application/__init__.py`: exports
- `backend/src/cv_masking/application/detection.py`: regions and review follow the policy
- Docs: `README.md`, `docs/stage-plan.md`, `docs/masking-policy.md` §5 (label colour, trimming, salary toggle) and §6 (fail-closed removal)

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, format, lint, typecheck, tests) | exit 0 |
| `scripts/check-repo-files.sh --all` | `154 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `120 files already formatted` / `All checks passed!` |
| `mypy` (strict) | `Success: no issues found in 118 source files` |
| `python scripts/run_pytest.py` | `400 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

75 new backend tests (325 → 400). All fixtures are generated at test time
from the synthetic values in `synthetic_redaction.py`.

- **`test_redaction_pdf.py`** runs the full pipeline: extraction, detection,
  redaction, then reopening the output.
  - Name, email, phone, and salary cannot be extracted afterwards.
  - Unredacted text survives and the page still renders.
  - Every region is labelled at ≥ 6 pt or solid, and labelled + solid equals
    the region count. A two-line region gets one label; a label that does not
    fit leaves a solid box.
  - **Tight-line acceptance test** at line heights 0.8, 1.0, and 1.2: the
    lines above and below stay intact and the target word's glyphs are gone.
    A canary test proves that untrimmed rectangles *would* damage the
    neighbouring lines, so the trim is load-bearing.
  - An embedded image outside the boxes is byte-identical after decoding (D-13).
  - Salary is redacted only with the toggle on. With it off, findings are
    reported but no regions are made.
  - Other cases: rotated pages; a rewrite with no regions; input bytes never
    modified.
  - Failures: unreadable, truncated, or encrypted input, and a region on a
    missing page.
  - A monkeypatched no-op `apply_redactions` is caught by the output check.
  - `RedactionResult` invariants hold, and logs contain no values.
- **`test_redaction_hidden.py`**:
  - Each of the six categories is classified correctly.
  - Each is removed on its own and all together. After removal the scan is
    empty, the hidden string is absent from the text *and* from every decoded
    PDF object, and visible words and the image are unchanged.
  - Each is refused without approval.
  - Render-mode-3 and zero-opacity text are flagged.
  - A layer MuPDF and the PDF rules disagree on fails closed.
  - The always-stripped components are removed without approval, and an
    incrementally saved input comes out as a single revision.
- **`test_pdf_content.py`**:
  - hidden painting is removed while state operators are kept;
  - `'` and `"` keep their line movement;
  - nested blocks stay hidden;
  - hidden XObjects are removed, and an inline image containing `EMC` bytes is
    handled;
  - strings with parentheses and escapes are one operand;
  - `#xx` names are decoded;
  - nine malformed streams and an unknown layer name fail closed.
- **`test_redaction_service.py`**:
  - a successful redaction writes a new object, and the input hash is unchanged
    before and after;
  - a redactor failure is passed through with nothing stored;
  - an output write failure gives `REDACT_OUTPUT_WRITE_FAILED`;
  - a tampered input is refused, and an input changed during redaction deletes
    the output;
  - a failed detection or a missing redactor raises `InvariantError`;
  - logs contain counts only.
- **`test_redaction_boundaries.py`** (architecture): `redactor.py` and
  `content.py` call no drawing or overlay API (`draw_*`, `insert_text*`,
  `insert_htmlbox`, `insert_image`, `new_shape`, `show_pdf_page`, rect,
  free-text, and stamp annotations, `set_opacity`). They must call
  `add_redact_annot` and `apply_redactions`. This makes an overlay-only
  redaction impossible without failing the build.

## Security/privacy review

- **No new dependency, subprocess, or network call.** PyMuPDF was already a
  runtime dependency (AGPL, recorded in Stage 6). All work is in memory. The
  only file writes go through the existing output store.
- **Input is immutable.** The redactor gets bytes and returns new bytes. The
  service checks the input hash before and after, and deletes the output if it
  changed. Tests prove the stored file's SHA-256 is unchanged.
- **True removal, not overlay.** Enforced by the architecture test and the
  output self-check: no text may remain under any region.
- **Fail-closed everywhere.** Parser surprises, render differences, leftover
  hidden content, and stripped keys that reappear all refuse the output rather
  than release a partial result.
- **No values in logs or results.** `RedactionResult` and `RedactionOutcome`
  carry bytes or an object reference, a code, and counts. Test assertions use
  booleans, counts, and case indexes.
- **The agent never read, listed, or searched `data/`.** The before/after images
  used in the report were rendered from the synthetic fixture into `/tmp`.

## Known limitations

- **Viewer-dependent layers are refused, not cleaned.** Some optional-content
  membership dictionaries (e.g. `/P /AllOn` over an OFF layer) are drawn by
  MuPDF but hidden under the PDF rules. The render comparison catches the
  disagreement and the document fails with `REDACT_SANITIZE_FAILED`. That code
  is marked retryable, but retrying cannot help (see question 1).
- **Hidden-text removal is by rectangle.** Visible glyphs overlapping invisible
  text are removed with it, without a black box, so the output may show a gap.
- **Hidden-layer text that shares a text block with visible text** and moves
  the text position in ways the filter can't keep would change the render, so
  it fails closed rather than shifting visible text.
- **Not stripped:** tagged-PDF structure (`StructTreeRoot`, which can hold alt
  text) and `PieceInfo` private data. See question 2.
- **Labels use Helvetica** (ASCII labels only), in a fixed grey on black.
- **Not wired into the state machine, API, or UI.** Stage 11 adds independent
  verification and Stage 12 the jobs.

## Manual verification steps

1. `make check` passes.
2. For a visual check on synthetic data only, run the redactor on
   `cv_pdf()` from `tests/application/synthetic_redaction.py` and render page 1
   before and after with `page.get_pixmap()`. You should see black boxes with
   grey `[NAME]`, `[EMAIL]`, `[PHONE]`, `[SALARY]` labels, field labels such as
   "Email:" still visible, and the three tight lines intact. Never do this with
   a real CV.

## Questions/decisions for the tech lead

1. **Make `REDACT_SANITIZE_FAILED` non-retryable?** Every cause found so far
   (viewer-disagreement layers, a malformed content stream) is deterministic,
   like `MAP_FAILED` in Stage 9.
2. **Strip `StructTreeRoot` alt text and `PieceInfo` always?** They can hold
   text that is not on the page. Removing `StructTreeRoot` loses accessibility
   tags.
3. **`MAP_AMBIGUOUS` with salary OFF.** Overprinted salary words still set
   `MAP_AMBIGUOUS` (review) even though they are not redacted. Keep this, or
   limit it to redacted types like the low-confidence flag?
4. **Label colour.** Grey 0.9 replaces white in masking-policy §5. Please
   confirm.

## Suggested commit message

```text
feat(redact): permanent PDF redaction with labels, sanitization, and output self-check (Stage 10)

- PyMuPDF redaction annotations + apply_redactions; rects trimmed off neighbouring lines
- One fitted label per region or solid fill; salary regions follow the policy toggle
- Always-strip metadata; remove approved hidden content with fail-closed render check
- Output reopened and verified; RedactionService keeps inputs immutable (hash before/after)
- Fix Stage 6 scan: render mode 3 and zero-opacity text are now flagged
```
