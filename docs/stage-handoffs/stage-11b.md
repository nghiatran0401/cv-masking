# Stage 11b handoff — DOCX verification

## Stage and objective

Stage 11b extends the Stage 11 verifier to DOCX. A new `DocxVerifier`
inspector reads the stored output and source archives fresh. The existing
format-neutral `VerificationService` then:

- searches every part for distinctive source values;
- checks that each part's text is exactly the source text with labels in
  place of the redacted ranges;
- reruns the Stage 7 rules.

It returns `PASSED`, `REVIEW_REQUIRED`, or `FAILED` with `VERIFY_*` codes. It
uses nothing from the redactor. Wiring into jobs belongs to Stage 12.

## Architecture decisions

- **`adapters/docx/verifier.py` — `DocxVerifier`.**
  - It reuses two Stage 6b pieces: the archive reader (entry limits, ratio,
    unsafe names, no disk extraction) and the shared text walk. It imports
    nothing from `redactor.py` or `xmledit.py`; the architecture test now
    covers it.
  - **`VERIFY_OUTPUT_INVALID`:**
    - an OLE container, an unreadable or unsafe archive, or a zip bomb;
    - missing `[Content_Types].xml` or `word/document.xml`;
    - any `.xml`/`.rels` part that fails to parse with defusedxml (DTDs,
      entities, depth bound);
    - an internal relationship or content-type override pointing at a missing
      part.
  - **`VERIFY_STRUCTURE_MISMATCH`:** a source part is missing from the output
    and the policy does not remove it. Parts the policy removes: document
    properties, thumbnail, people, comments, embeddings, glossary, custom XML,
    `aFChunk`/attached-template targets, and their `_rels`.
  - **`VERIFY_RESIDUAL_METADATA`:**
    - any removed part is present, or there is any external relationship or
      `aFChunk`/`attachedTemplate` relationship;
    - any residue element in a `word/*.xml` part: field codes, `fldSimple`,
      settings history, tracked-change markup of every kind, comment anchors,
      objects, `altChunk`, data bindings, `customXml`, or hidden-text markers;
    - tooltips, `rsid*` attributes, or picture `descr`/`title`;
    - **D-36:** a style that hides text, directly or through `basedOn`, and is
      used by `pStyle`/`rStyle`/`tblStyle` or is a default style; or document
      defaults that hide text. In `styles.xml`, hidden-text markers are judged
      only by this rule, so an unused hiding style passes.
  - **Text model:** the output's text parts come from the shared walk, the
    same view detection used on the source.
  - **Raw material:** every text node, joined with spaces, and every attribute
    value of every XML part, plus the decoded bytes of other parts. Images and
    embedded fonts are not searched (D-13).
- **Service additions (`application/verification.py`).**
  - **DOCX text equality.** For each source text part, the expected text is
    the source text with every range the policy redacts replaced by its label.
    The ranges are rebuilt from the detection findings with the application's
    own `build_docx_ranges`, not taken from the redactor. The output part's
    text must match with all whitespace removed, because emptied paragraphs
    change line breaks. A difference gives `VERIFY_RESIDUAL_FINDING`. This
    covers the short and generic values the value search skips (D-37), and it
    fails any unexpected change to kept text.
  - **Faster, wider folding.** `fold` now strips combining marks with a regex,
    so multi-megabyte raw material folds at C speed. Raw material is folded
    like the text, so Vietnamese values are found inside XML as well.

## Files added/changed

- **Added**
  - `backend/src/cv_masking/adapters/docx/verifier.py`
  - `backend/tests/application/synthetic_docx_verification.py`
  - `backend/tests/application/test_docx_verification.py`
  - `docs/stage-handoffs/stage-11b.md`
- **Changed**
  - `backend/src/cv_masking/adapters/docx/__init__.py` (exports
    `DocxVerifier`)
  - `backend/src/cv_masking/application/verification.py` (DOCX text
    equality, regex folding, folded raw search)
  - `backend/tests/architecture/test_verification_boundaries.py`
  - `README.md`
  - `docs/stage-plan.md`
  - `docs/error-codes.md` (meaning of `VERIFY_RESIDUAL_FINDING`)

No new dependencies or subprocesses.

## Commands run and exact results

- `make check`:
  - file guard: `180 file(s) checked, none refused`;
  - ruff format and lint: `All checks passed!`;
  - mypy: `Success: no issues found in 133 source files`;
  - pytest: `572 passed in 39.73s`;
  - vitest: `3 passed (3)` files, `7 passed (7)` tests.
- `pytest tests/application/test_docx_verification.py`: `52 passed`.

## Tests added (`test_docx_verification.py`, 52 tests)

- **Passing outputs:**
  - a redacted DOCX passes, and neither stored file changes;
  - outputs with each hidden category removed, and all of them together,
    pass;
  - salary left by the toggle passes and fails under a salary-masking
    policy;
  - an unused hiding style passes.
- **Residual findings** (the prompt's list plus more):
  - a value in the text-box fallback copy;
  - a header value;
  - a name split across runs;
  - an NFD name;
  - a short value (`Nam`) where a label was;
  - changed kept text;
  - document properties, comments, field codes, the thumbnail, alt text and
    a hyperlink target. These last six are also asserted as
    `VERIFY_RESIDUAL_METADATA`.
- **Residual metadata:** `rsid`, `docVars`, a hidden run, a tracked insert, a
  tooltip, a title attribute, a used hiding style, a style based on a hiding
  style, a default hiding style, and document defaults that hide text.
- **Structure:** `styles.xml` removed along with its relationship and override
  gives only `VERIFY_STRUCTURE_MISMATCH`.
- **Invalid:** malformed XML, a DOCTYPE, a missing `document.xml`, a dangling
  relationship, a truncated archive, a non-zip file, an OLE container, and a
  zip bomb.
- **Boundaries:** an unreadable source gives `INTERNAL_ERROR`.
- **Job gate:** a real `PASSED` result gives `COMPLETED` for a DOCX job; a
  leak gives `FAILED` with `VERIFY_RESIDUAL_FINDING`.

I checked by hand which check catches each value tamper:

- The text-equality check alone catches the short value and the changed kept
  text.
- The raw search alone catches document properties, comments, field codes,
  the thumbnail, alt text and the hyperlink target.

## Security/privacy review

- No network access, dependencies or subprocesses.
- Source values exist only as in-memory patterns and expected text for one
  call. Results carry codes only.
- Test ids and assertion messages name the tamper, never a value. Fixtures are
  synthetic: Nguyễn Văn Mẫu, `example.test`, the `0900000000` shape, Jane
  Example.
- The verifier only reads, and a test checks both stored hashes.
- The runtime `data/` folder was not read or searched.

## Known limitations

- Rendering in Microsoft Word is not verified; Word automation is forbidden.
  Package validity is checked structurally: parts parse, relationships and
  overrides resolve, and nothing is missing.
- Until Stage 12 changes the Stage 6b extractor (D-32), a source with hidden
  content has no extracted document. The tests build the source text model
  with the shared walk, which is what the extractor will return after
  Stage 12.
- Text-equality false failures are possible in one case. If detection finds a
  value in only one copy of a text box whose copies are identical, the
  redactor mirrors the edit into the other copy, so the output no longer
  matches the expected text and verification fails. This fails closed.
  Findings inside legacy `w:object` also fail, consistent with D-35.
- Images and embedded fonts are not searched (D-13).

## Manual verification steps

1. `make check`
2. `cd backend && uv run --locked python scripts/run_pytest.py tests/application/test_docx_verification.py -v`

## Questions/decisions for the tech lead

None new. The rules follow D-35, D-36 and D-37.

## Suggested commit message

`feat(verify): independent DOCX output verification with package checks, residue scan, style-hidden text, and exact text comparison (Stage 11b)`
