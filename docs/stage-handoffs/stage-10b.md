# Stage 10b handoff — Permanent DOCX redaction

## Stage and objective

Stage 10b turns DOCX findings into a new, permanently redacted DOCX. Each mapped
character range is removed from the XML text and replaced with the policy label,
in every content part and in both copies of `mc:AlternateContent`. The redactor
also applies the always-strip list (supported-pdf.md §6.3) and removes every
hidden-content category (§6.4). The input is never modified. The result is
reopened and checked before it is returned. It is not wired into jobs, the API,
or the UI yet (Stage 12).

## Architecture decisions

- **Ranges are domain objects.**
  - `DocxRedactionRange(part_name, start, end, entity_type, finding_ids)` in
    `domain/findings.py` is the DOCX counterpart of `RedactionRegion`. It holds
    no text.
  - `application/mapping.build_docx_ranges` merges overlapping findings within
    one part. It labels each merged range with the same winner rule as PDF.
  - `DetectionOutcome.docx_ranges` covers only the types the policy redacts,
    so salary follows the toggle.
- **One port, two units.**
  - `DocumentRedactor[Unit]` is generic.
  - `PdfRedactor = DocumentRedactor[RedactionRegion]` and
    `DocxRedactor = DocumentRedactor[DocxRedactionRange]`.
  - `RedactionService(inputs, outputs, *, pdf=None, docx=None)` picks the
    redactor by format. A missing redactor is an `InvariantError`, raised before
    any I/O.
- **Shared text walk (`adapters/docx/text.py`).**
  - The extractor and the redactor use the same `walk_part`, so redaction
    offsets are exactly the extraction offsets.
  - Each run's text is NFC. The part is not normalized again as a whole,
    because a combining mark at the start of a run would compose with the
    previous run and shift every later offset. This fixed a latent Stage 6b
    crash: such a document raised `InvariantError` from `DocxExtractor.extract`.
- **Byte-splice XML editor (`adapters/docx/xmledit.py`).**
  - Each part is parsed by defusedxml, which gives the tree, and by stdlib
    expat, which gives the byte offsets. The two element sequences must agree
    tag by tag, or the edit is refused.
  - Edits splice the original bytes. Namespace prefixes, declarations, comments
    and every unedited byte stay identical, and unrelated parts are copied
    unchanged.
  - Only four operations exist: delete an element, unwrap an element, drop
    attributes, and replace the text of a `w:t`. `set_text` refuses any other
    element.
  - Formatting cannot be expressed, so formatting-only redaction is impossible
    by construction. An architecture test pins the public API and forbids tree
    mutation, tree serialization, and formatting-property names.
  - It refuses DTDs, entity declarations, UTF-16 input and non-UTF-8
    declarations.
- **`DocxXmlRedactor` (`adapters/docx/redactor.py`).**
  1. Re-extracts the input. Any refusal, and any review other than hidden
     content, gives `REDACT_FAILED`.
  2. Per text part:
     - maps each range onto the `w:t` pieces it touches;
     - writes the label into the first piece, so it keeps that run's
       formatting, and empties the rest;
     - mirrors the edits into the other copy of an `mc:AlternateContent` pair
       when the copies' texts are equal.

     A range that touches no piece, or runs past the end, fails closed.
  3. Sanitizes the package:
     - drops the §6.3 and §6.4 parts, external relationships, and
       relationships to dropped parts, plus their references;
     - deletes field codes, settings history, deleted and moved-from text,
       old formatting, comment anchors, objects, `altChunk` and data bindings;
     - unwraps insertions, `moveTo`, `fldSimple` and `customXml`;
     - removes vanished runs;
     - drops picture `descr`/`title`, hyperlink tooltips and `rsid*` attributes;
     - drops content-type overrides for removed parts.
  4. Writes a fresh ZIP. `[Content_Types].xml` comes first, with fixed
     timestamps and deflate compression.
  5. Self-check. It reopens the output with the Stage 6b extractor and requires:
     - no hidden content;
     - exactly the predicted text in every part;
     - no residue from the strip list.

     Otherwise it returns `REDACT_SANITIZE_FAILED` or `REDACT_FAILED`.
- **Output name.** Outputs are stored as `<uuid>.docx` by the output store. The
  `redacted-<uuid>.docx` name is applied at download (Stage 13), the same as
  for PDF.
- **`remove_hidden` is kept for now.** It keeps the port the same as the PDF
  redactor's. Hidden content without the flag is refused with
  `REDACT_SANITIZE_FAILED`. Stage 12 removes the flag (D-32).

## Files added/changed

- **Added**
  - `backend/src/cv_masking/adapters/docx/text.py`
  - `backend/src/cv_masking/adapters/docx/xmledit.py`
  - `backend/src/cv_masking/adapters/docx/redactor.py`
  - `backend/tests/application/synthetic_docx_redaction.py`
  - `backend/tests/application/test_docx_redaction.py`
  - `backend/tests/application/test_docx_xmledit.py`
  - `docs/stage-handoffs/stage-10b.md`
- **Changed**
  - `adapters/docx/__init__.py` (exports `DocxXmlRedactor`)
  - `adapters/docx/extractor.py` (uses the shared walk)
  - `domain/findings.py`
  - `application/mapping.py`
  - `application/detection.py`
  - `application/redaction.py`
  - `ports/redaction.py`
  - `tests/application/test_mapping.py`
  - `tests/application/test_redaction_service.py`
  - `tests/architecture/test_redaction_boundaries.py`
  - `tests/domain/test_no_pii_fields.py`
  - `backend/pyproject.toml`, `backend/uv.lock`
  - `README.md`
  - `docs/stage-plan.md`
  - `docs/supported-pdf.md` (§6.3 now lists tooltips, the `fldSimple` unwrap
    and the mail-merge source)

## Dependency

`python-docx==1.2.0` was added to the **dev group only**. It pulls in
`lxml 6.1.3`, a native extension. It is the independent OOXML parser the
acceptance criterion asks for. Tests use it to open every output and to check
the label's run formatting.

- **Security:** it is a pure local parser with no network access, and it only
  opens synthetic files built in memory.
- **Packaging:** it is not a runtime dependency and is not imported by `src/`,
  so the shipped app is unchanged.
- **Runtime:** the redactor uses only the standard library and the existing
  defusedxml. No subprocess was added.

## Commands run and exact results

- `make check`:
  - file guard: passed;
  - ruff format and lint: `All checks passed!`;
  - mypy: `Success: no issues found in 124 source files`;
  - pytest: `459 passed`;
  - vitest: `3 passed (3)` files, `7 passed (7)` tests.
- `pytest tests/application/test_docx_redaction.py tests/application/test_docx_xmledit.py`:
  52 tests collected, all passing.

## Tests added

- **`test_docx_redaction.py` (38 tests).** Built from synthetic parts (a name
  split across runs with NFD, a hyperlink, header, footnotes, text box, table,
  field code, alt text, settings, docProps, people, thumbnail, media).
  - Every redacted value is absent from every decompressed part, searched as
    raw NFC and NFD bytes.
  - The output opens with python-docx. The label keeps the first run's
    formatting.
  - Unredacted text and structure survive. Namespace prefixes and
    `mc:Ignorable` are preserved. Unrelated parts are byte-identical, and no
    element is added.
  - AlternateContent Choice and Fallback are both redacted.
  - The salary toggle is honoured in both directions.
  - Always-strip items are removed without any hidden-content flag.
  - Each hidden-content category is removed, and all of them together.
    Tracked changes are accepted.
  - Hidden content without the flag is refused. The input bytes are unchanged.
  - Fail-closed cases: unreadable input, unplaceable ranges, a UTF-16 part.
  - A combining mark that starts a run keeps offsets aligned.
  - A monkeypatched no-op text edit gives `REDACT_FAILED`. A no-op strip gives
    `REDACT_SANITIZE_FAILED`.
  - Logs carry no values.
- **`test_docx_xmledit.py` (14 tests).**
  - An unedited part is returned as the same bytes.
  - Exact bytes after delete, unwrap, attribute drop and text edits.
  - Attribute values containing `>` and quotes.
  - A self-closing `w:t`, with `xml:space` handling and escaping.
  - Edits inside a deleted element are skipped.
  - Only `w:t` accepts text. Elements from another part are refused.
  - DTD, UTF-16 and latin-1 input are refused. A BOM does not shift offsets.
  - Attributes are matched by namespace, not by prefix.
- **`test_mapping.py`.**
  - DOCX findings produce `docx_ranges`.
  - Ranges merge overlaps within one part only and pick the label winner.
  - PDF and DOCX builders ignore each other's findings.
  - Range invariants.
- **`test_redaction_service.py`.** End-to-end DOCX run through the service with
  the real detector. It produces a new object, the stored input hash is
  unchanged, and no values appear in the output.
- **`test_redaction_boundaries.py`.**
  - DOCX redaction modules have no tree mutation or serialization calls and no
    formatting-property names.
  - `XmlPart`'s public API is exactly the removal and text-replacement set.
- **`test_no_pii_fields.py`.** `DocxRedactionRange` has been added to the field
  allowlist, and its `part_name` is validated.

## Security/privacy review

- No network calls, telemetry or subprocesses.
- The only new dependency is dev-only.
- No value reaches logs, errors or test output. Test ids and assertion messages
  use indexes or types.
- Fixtures use only synthetic values: Nguyễn Văn Mẫu, `example.test`, the
  `0900000000` shape, and Công ty TNHH Ví Dụ.
- The input is never written. The service re-verifies its hash after redaction.
- Untrusted XML is refused unless both parsers agree. There is no DTD or entity
  expansion, and depth is bounded.
- No formatting-based hiding is possible (see the architecture tests).
- The runtime `data/` folder was not read or searched.

## Known limitations

- Text inside `w:object` (legacy VML/OLE) is deleted along with the object. If
  a finding falls inside it, the self-check fails closed rather than redacting.
- Hidden text is detected only from direct `w:vanish` on runs. Vanish that
  comes from a style is not detected (same as Stage 6b).
- AlternateContent copies whose texts differ are not mirrored. The finding
  still maps to its own copy, and the other copy is redacted only by its own
  findings.
- The D-32 code change (removing `remove_hidden` and the hidden-content review
  path) is deferred to Stage 12.
- An independent search of the output for the source values is left to
  Stage 11b.
- Word itself was not used to open the outputs (AGENTS.md forbids automating
  Word). They were checked with python-docx and the Stage 6b extractor.

## Manual verification steps

1. `make check`
2. `cd backend && uv run --locked python scripts/run_pytest.py tests/application/test_docx_redaction.py -v`
3. Optionally, from a test, save the output of `DocxXmlRedactor().redact(cv_docx(), ...)`
   to a temporary file and open it in Word by hand. Use only the synthetic
   fixture.

## Questions/decisions for the tech lead

Resolved after review:

- **D-35:** findings inside legacy `w:object` content keep failing closed.
- **D-36:** Stage 11b fails outputs that use a style which hides text.

## Suggested commit message

`feat(docx): permanent DOCX redaction by XML text removal, strip list, hidden-content removal, output self-check (Stage 10b)`
