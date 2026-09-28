# Stage 11 handoff — Independent verification

## Stage and objective

Stage 11 adds an independent verifier for redacted PDFs. It reads the stored
output and source back from storage and opens them with fresh parser handles.
It returns `PASSED`, `REVIEW_REQUIRED`, or `FAILED` with `VERIFY_*` codes. It
uses nothing from the redactor. Wiring into jobs (`record_verification`) belongs
to the Stage 12 worker. The domain already allows only a `PASSED` result to
reach `COMPLETED`, and a test drives real results through that gate.

## Architecture decisions

- **Port `ports/verification.py`.**
  - `OutputInspector.inspect(output, source) -> OutputInspection` is one
    adapter per format.
  - An inspection holds three things: the output's extracted text model (all
    text, including text a reader cannot see), decoded raw objects for a plain
    value search, and structural failure codes.
  - `InspectionError` means the source itself could not be read.
- **`application/verification.py` — `VerificationService`.** It is
  format-neutral, so Stage 11b adds only a DOCX inspector.
  1. Checks the hashes of the stored source and output, then reads both.
  2. Runs the format inspector.
  3. **Value search.** Every distinctive source value of a redacted type is
     searched for in the output's folded text and in its raw objects. Folding
     means diacritic-free, case-folded and NFC/NFD-insensitive; separators of up
     to three characters are allowed between tokens, and matches respect word
     boundaries. A hit gives `VERIFY_RESIDUAL_FINDING`.
  4. **Position check.** Any output word whose centre lies inside a redacted
     PDF finding box, other than a label, gives `VERIFY_RESIDUAL_FINDING`.
  5. **Detector rerun.** The deterministic Stage 7 rules run on the output.
     A match of a type the policy redacts, at or above the redact threshold,
     gives `VERIFY_RESIDUAL_DETECTION`. A match between the discard and redact
     thresholds gives `REVIEW_REQUIRED`, which becomes `VERIFY_REVIEW` on the
     job and is deny-only. Matches that are only labels are ignored.
  6. Storage failures return the storage code. An unreadable source or a
     detector error returns `INTERNAL_ERROR`, which is retryable.
- **Which values are searched.** Only values that are distinctive enough that
  a hit means a leak:
  - names with two or more tokens;
  - email, phone, national ID, passport and URL values;
  - full dates of birth;
  - addresses with a number and three or more tokens;
  - and in every case at least 6 letters or digits.

  Short or generic values (`Nam`, `Việt Nam`, `1990`, `Hà Nội`) also occur in
  kept text, such as work history, and would fail good outputs. Those are
  covered by the position check and the detector rerun instead.
- **Only Stage 7 rules are rerun (`PatternDetector`).** The Stage 8 name and
  section heuristics depend on layout, and redaction changes the layout. For
  example, after the name is redacted, the next line becomes the "first line"
  and a job title can look like a name. So names are verified by the value
  search and the position check. `PatternDetector` reuses the Stage 7 rules
  unchanged.
- **`adapters/pdf/verifier.py` — `PyMuPDFVerifier`.** It imports nothing from
  the redactor (an architecture test enforces this).
  - Opens the output fresh. It is invalid if it doesn't start with `%PDF-`,
    fails to open, is encrypted, needed repair, has 0 or more than 30 pages, or
    is over the xref limit.
  - Renders every page. A rendering error gives `VERIFY_OUTPUT_INVALID`.
  - Compares page counts with the source.
  - Gives `VERIFY_RESIDUAL_METADATA` for any of the following:
    - document info or XMP metadata, or outlines;
    - any annotation, link or widget;
    - more than one `startxref`, meaning earlier revisions remain;
    - any Stage 6 hidden-content category;
    - any object or trailer key that masking-policy §6 always removes
      (actions, JavaScript, embedded files, forms, outlines, page labels,
      metadata, tagged structure, `PieceInfo`, thumbnails, optional content,
      URIs). It uses its own list.
  - Extracts words with no clip and no visibility filter, so invisible and
    off-page text is still searched.
  - Collects every non-font, non-image object and stream (capped at 64 M
    characters, otherwise invalid) for the raw value search.
  - Does not inspect image content (D-13).

## Files added/changed

- **Added**
  - `backend/src/cv_masking/ports/verification.py`
  - `backend/src/cv_masking/application/verification.py`
  - `backend/src/cv_masking/adapters/pdf/verifier.py`
  - `backend/tests/application/synthetic_verification.py`
  - `backend/tests/application/test_verification.py`
  - `backend/tests/architecture/test_verification_boundaries.py`
  - `docs/stage-handoffs/stage-11.md`
- **Changed**
  - `adapters/detection/detector.py` (adds `PatternDetector`; the recognizers
    are built by a shared function)
  - `adapters/detection/__init__.py`
  - `adapters/pdf/__init__.py`
  - `application/__init__.py`
  - `README.md`
  - `docs/stage-plan.md`

No new dependencies or subprocesses.

## Commands run and exact results

- `make check`:
  - file guard: `173 file(s) checked, none refused`;
  - ruff format and lint: `All checks passed!`;
  - mypy: `Success: no issues found in 130 source files`;
  - pytest: `520 passed in 38.16s`;
  - vitest: `3 passed (3)` files, `7 passed (7)` tests.
- `pytest tests/application/test_verification.py`: `59 passed`.

## Tests added

- **`test_verification.py` (59 tests).**
  - **Passing outputs:**
    - a redacted CV passes, and neither stored file changes;
    - outputs with each hidden-content category removed, and all of them
      together, pass;
    - salary left by the toggle passes. The same output fails with
      `VERIFY_RESIDUAL_DETECTION` under a policy that masks salary.
  - **Tampered outputs:**
    - the unredacted input fails with a residual finding (primary code) and a
      residual detection;
    - source values put back fail with a residual finding: visible, NFD,
      diacritic-free, invisible (render mode 3), off-page, upper-case, and
      only inside a raw PDF object;
    - each of the following fails with `VERIFY_RESIDUAL_METADATA`: document
      info, XMP, a link, an annotation, an embedded file, JavaScript, an
      outline, tagged structure, invisible text, an incremental update;
    - a stray word inside a redacted box fails with a residual finding;
    - a new synthetic email fails with a residual detection only;
    - an extra page fails with a page-count mismatch;
    - truncated, non-PDF and header-only outputs fail with
      `VERIFY_OUTPUT_INVALID`.
  - **Rerun rules:**
    - label-only matches and discarded matches pass;
    - uncertain matches give `REVIEW_REQUIRED`;
    - certain matches fail;
    - types the policy keeps are ignored;
    - `PatternDetector` emits no name types.
  - **Value-search rules:** which values are searched, the normalization, and
    word boundaries.
  - **Failures and boundaries:**
    - a tampered stored output gives `STORAGE_INTEGRITY_FAILED`;
    - an unreadable source gives `INTERNAL_ERROR`;
    - a failed detection or mismatched formats raise `InvariantError`;
    - logs carry codes only.
  - **Job gate:** a real `PASSED` result gives `COMPLETED`, and a real residual
    result gives `FAILED` with `VERIFY_RESIDUAL_FINDING`.
- **`test_verification_boundaries.py`.**
  - The verifier modules import no redaction code.
  - Production verification code contains no mock, fake or stub.

## Security/privacy review

- No network access, dependencies or subprocesses.
- Source values exist only in memory, as compiled search patterns during one
  call. They are never stored, logged or returned. Results carry only codes,
  ids, the verifier version and a time.
- Test ids and assertion messages use tamper names and indexes, never values.
  Fixtures are synthetic: Nguyễn Văn Mẫu, `example.test`/`example.invalid`,
  the `0900000000` shape, and Example Bank Ltd.
- The verifier only reads stored files, and a test checks that both hashes are
  unchanged.
- The runtime `data/` folder was not read or searched.

## Known limitations

- Rendering is checked only for errors. Pixels are not compared with the source.
- Short or generic values are not searched as text anywhere in the output, only
  checked by position and by the detector rerun. A generic value copied to a
  new place on the page would not be caught.
- Text inside images is not inspected (D-13). The same applies to glyphs drawn
  as vector paths.
- The raw search sees only literal strings. Text encoded as glyph ids in
  content streams is covered by extraction instead.
- `remove_hidden` on the redactor and the extractors' hidden-content review
  path remain until Stage 12 (D-32).
- Verification adds about 0.3 s per synthetic PDF. The full test suite went
  from about 15 s to about 40 s.

## Manual verification steps

1. `make check`
2. `cd backend && uv run --locked python scripts/run_pytest.py tests/application/test_verification.py -v`

## Questions/decisions for the tech lead

- Please confirm two choices:
  - The rerun uses only the deterministic Stage 7 rules. Names are covered by
    the value search and the position check.
  - Only distinctive values are searched anywhere in the output.
- Please confirm that an uncertain residual detection should be a deny-only
  `REVIEW_REQUIRED` (`VERIFY_REVIEW`) rather than `FAILED`.

## Suggested commit message

`feat(verify): independent PDF output verification with value search, position check, detector rerun, and structural checks (Stage 11)`
