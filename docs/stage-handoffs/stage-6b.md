# Stage 6b handoff — DOCX validation and extraction

## Stage and objective

Stage 6b classifies uploaded DOCX files and, when they are supported, extracts
the same format-neutral text model as Stage 6 (reading-order NFC text and
character spans). Hidden content from supported-pdf.md §6 is detected and held
for review. There is still no detection or redaction. Starting a batch does not
run validation; Stage 12 owns the worker.

## Architecture decisions

- **Same port and text model as Stage 6.** `DocumentExtractor.extract` returns
  `ExtractionResult`. DOCX `TextPart`s use `part_name` (for example
  `word/document.xml`) and `TextSpan` character ranges with empty boxes. Stage 7
  can consume the model unchanged.
- **`HiddenContentAlert` is pages XOR parts.** PDF alerts still pass page
  numbers. DOCX alerts pass sorted unique lowercase part kinds (`document`,
  `header`, `comments`, …), never filenames or text.
- **Adapter `adapters/docx`.** `read_docx_archive` opens the ZIP in memory,
  never extracts to disk, and enforces entry count (2,000), per-entry size
  (50 MiB), total uncompressed size (100 MiB), 100:1 compression ratio, and
  safe names (no NUL, `\`, `:`, leading `/`, or `..` segments). `DocxExtractor`
  classifies and walks XML.
- **XML parser is `defusedxml` 0.7.1, not lxml.** This stage is read-only
  extract. Standard-library ElementTree is unsafe for untrusted XML (DTDs /
  entities). lxml is reserved for Stage 10b if write-back must preserve Word
  namespace prefixes. OLE magic is duplicated locally so the adapter does not
  import `application.identify`.
- **`ValidationService` is a format → extractor map.** PDF and DOCX both
  validate. Logs still say `pages=` for the part count; that word is already
  on the no-PII allowlist.
- **Classification order:** empty / OLE encrypted → archive safety → missing
  `[Content_Types].xml` or `word/document.xml` → macro/template markers → XML
  parse (DTD/entity/depth) → hidden scan + text extract → too-large text →
  hidden review → no visible text → `ExtractedDocument`.
- **Extracted:** body, tables, headers, footers, footnotes, endnotes, both
  `mc:AlternateContent` copies, content controls (`w:sdt`), and field *results*.
  `w:instrText`, vanished runs, `w:del` / `w:moveFrom`, comments parts, and
  hyperlink targets are not in the text model.
- **Always-strip items** (core properties, field codes, mailto targets) are
  omitted from the text model and do not raise an HR alert. Removal from the
  file is Stage 10b.
- **Not wired into the HTTP API or `start_batch`.** Tests construct
  `ValidationService` with `DocxExtractor`. Stage 12 will call it from the
  worker.

## New dependency: defusedxml 0.7.1

| | |
|---|---|
| Purpose | Parse untrusted Office XML with DTDs, entities, and network disabled |
| License | MIT |
| Network | None. No telemetry. Air-gapped after install. |
| Native code | No. Pure-Python wheel. |
| Packaging | One extra wheel (~25 KB). No extra subprocess. `lxml` is not added. |

## Files added/changed

Added:
- `backend/src/cv_masking/adapters/docx/{__init__,archive,extractor}.py`
- `backend/tests/application/{synthetic_docxs,test_docx_extract}.py`
- `docs/stage-handoffs/stage-6b.md`

Changed:
- `backend/src/cv_masking/domain/limits.py`: DOCX archive, text, and XML-depth caps
- `backend/src/cv_masking/domain/hidden.py`: DOCX categories; alerts take pages or parts
- `backend/src/cv_masking/application/validation.py`: format → extractor map
- `backend/tests/application/test_extract.py`: ValidationService now accepts DOCX
- `backend/pyproject.toml` / `uv.lock`: `defusedxml==0.7.1`; mypy override
- Docs: `README.md`, `docs/stage-plan.md`, `docs/supported-pdf.md` §6.1

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `126 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `90 files already formatted` / `All checks passed!` |
| `npm run format:check`, `npm run lint` | pass |
| `mypy` (strict) | `Success: no issues found in 88 source files` |
| `python scripts/run_pytest.py` | `187 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

Thirteen new backend tests (174 → 187):

- **Supported layouts:** header, footnote, Vietnamese NFD name (NFC in the
  model), a name split across runs, a table cell, a content control, both
  AlternateContent text-box copies, and a field *result*. `instrText`, a mailto
  target, and `docProps` creator are absent from the text. A second extract is
  identical.
- **Unsupported (8 cases):** encrypted OLE, empty, oversized stored text,
  path-traversal entry name, zip-bomb ratio, DTD/XXE, a PDF stub, and a
  macro-enabled package.
- **Hidden content:** comments via `ValidationService` → `REVIEW_REQUIRED` /
  `DOCX_HIDDEN_CONTENT`; tracked changes and vanish via the extractor. Alert
  `repr` contains no comment text, inserted name, vanished text, or
  `comments.xml`.
- **Validation service:** supported DOCX → `QUEUED`; extracted tokens are
  absent from logs.

All DOCX files are generated at test time. None are committed (the file guard
would refuse ZIP/OLE magic).

## Security/privacy review

- **No remote I/O.** `defusedxml` forbids DTDs, entities, and network. Archive
  reads stay in memory. `pytest-socket` still blocks sockets. Bind host remains
  `127.0.0.1`.
- **No extracted text in persistence or logs.** Validation logs document id,
  `passed`/`review`/`failed`, part count (as `pages=`), and hidden-alert count
  only. Alerts are category/count/part-kind. SQLite schema is unchanged.
- **Parser and archive errors become codes.** Exception text is not logged or
  returned. Unsafe names fail closed (`DOCX_UNSAFE_ARCHIVE`).
- **Inputs are not overwritten.** Extract opens a copy from `InputStore`.
- **Test data** is synthetic. The agent never read, listed, or searched `data/`.
- **Layering.** The DOCX adapter does not import `application`.

## Known limitations

- **Validation is not started from the API.** Documents stay `UPLOADED` after
  `start_batch` until Stage 12.
- **Character-to-run mapping is offset-only.** Spans record `[start, end)` in
  the part text. Stage 10b will map those ranges back onto XML runs.
- **Always-stripped items are not removed from the file** (Stage 10b). They are
  excluded from the text model and are not hidden-content alerts.
- **Macro/template** is also rejected at upload (Stage 5). The extractor
  re-checks content types and `word/vbaProject*` as defense in depth.
- **Resource limits** besides the archive caps wait for Stage 14, which may
  tighten them.
- **PyMuPDF + pytest** is unchanged: use `make test` or
  `python scripts/run_pytest.py`.

## Manual verification steps

1. `make check` passes with 187 backend tests and the existing frontend tests.
2. Prefer the unit tests; they generate the DOCX files. Do not point the
   extractor at a real CV.

## Questions/decisions for the tech lead

None new. Stage 12 should call `ValidationService.validate` for each uploaded
PDF *and* DOCX after `start_batch`. lxml stays out until Stage 10b write-back
proves it is required.

## Suggested commit message

```text
feat(docx): validate and extract text from DOCX archives (Stage 6b)

- In-memory ZIP + defusedxml emit the same text model as PDF; no text is stored
- Archive attacks, macros, encrypted OLE, and hidden content fail closed
```
