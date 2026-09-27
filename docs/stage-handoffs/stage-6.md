# Stage 6 handoff — PDF validation and extraction

## Stage and objective

Stage 6 classifies uploaded PDFs and, when they are supported, extracts a
format-neutral text model (reading-order NFC text, word spans, and bounding
boxes). Hidden content from supported-pdf.md §4 is detected and held for review.
There is still no detection, redaction, or DOCX parsing. Starting a batch does
not run validation; Stage 12 owns the worker.

## Architecture decisions

- **Text model lives on the ports, not in the domain.** Domain stays free of
  document text. `ports/extraction.py` defines `TextSpan`, `TextPart`,
  `ExtractedDocument`, `ExtractionResult`, and `DocumentExtractor`. Hidden
  alerts (`domain/hidden.py`) carry only category, count, and page numbers.
- **Adapter `adapters/pdf` uses PyMuPDF 1.28.2** (`import pymupdf`). It opens
  bytes in memory, never writes the input, and suppresses MuPDF console
  messages so parser text cannot leak to stderr.
- **Application `ValidationService`** takes an uploaded PDF, starts validation,
  and records one of: `QUEUED`, `REVIEW_REQUIRED`, or `FAILED`. The extracted
  model is returned to the caller and is never written to SQLite, disk, or logs.
- **Classification order:** encrypted → xref cap → zero pages → too many pages
  → per-page text/hidden scan. Blocking review reasons win over hidden-content
  review (HR can only delete when both apply). Hidden-only review is
  `PDF_HIDDEN_CONTENT` (approvable later).
- **Minimum text:** 8 non-whitespace characters per page (`MIN_PAGE_TEXT_CHARS`).
  Below that, image-only pages become `PDF_NO_TEXT_LAYER`; unmapped glyphs
  (`U+FFFD` or empty text objects) become `PDF_TEXT_UNRELIABLE`.
- **Provisional xref cap:** 50,000 → `PDF_RESOURCE_LIMIT`. Stage 14 sets the
  final resource limits.
- **Invisible text** is excluded from the text model (render mode 3, size &lt; 2 pt,
  white fill, or outside the crop box) and counted as hidden.
- **Link annotations** are not an HR alert (always-stripped later). Comment and
  markup annotations, attachments, forms, JavaScript/Launch/SubmitForm/ImportData,
  hidden optional-content groups, and portfolios are.
- **Not wired into the HTTP API or `start_batch`.** Tests construct
  `ValidationService` with `PyMuPDFExtractor`. Stage 12 will call it from the
  worker. This keeps `create_app()` free of the native library.
- **Pytest runner.** PyMuPDF 1.28 segfaults if its native module is first
  imported after pytest has started, and again in C++ destructors at process
  exit. `make test` / `make check` run
  `python scripts/run_pytest.py`, which imports `pymupdf` first and leaves via
  `os._exit`. Plain `uv run pytest` is unsafe on this version.

## Files added/changed

Added:
- `backend/src/cv_masking/domain/hidden.py`
- `backend/src/cv_masking/ports/extraction.py`
- `backend/src/cv_masking/adapters/pdf/{__init__,extractor}.py`
- `backend/src/cv_masking/application/validation.py`
- `backend/tests/application/{synthetic_pdfs,test_extract}.py`
- `backend/scripts/run_pytest.py`
- `docs/stage-handoffs/stage-6.md`

Changed:
- `backend/src/cv_masking/domain/limits.py`: `MIN_PAGE_TEXT_CHARS = 8`
- `backend/src/cv_masking/application/__init__.py`: export validation types
- `backend/pyproject.toml` / `uv.lock`: `pymupdf==1.28.2`; mypy override for
  `pymupdf` / `fitz`
- `backend/tests/application/test_no_pii_persisted.py`: log-word allowlist
- `Makefile`: backend tests go through `scripts/run_pytest.py`
- Docs: `README.md`, `docs/stage-plan.md`, `docs/supported-pdf.md` (8-character
  page minimum)

## New dependency: PyMuPDF 1.28.2

| | |
|---|---|
| Purpose | PDF open/classify/extract (required by the Stage 6 prompt) |
| License | AGPL-3.0 or Artifex commercial. Bank legal must confirm the path before any distribution beyond the PoC (SECURITY.md §4). |
| Network | None. No telemetry, license callback, or cloud dependency. Air-gapped after install. |
| Native code | Yes (MuPDF C library). Wheels for macOS/Linux/Windows. |
| Packaging | One extra wheel (~23 MB). No extra subprocess. Interactive docs stay disabled. |

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `117 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `85 files already formatted` / `All checks passed!` |
| `npm run format:check`, `npm run lint` | pass |
| `mypy` (strict) | `Success: no issues found in 83 source files` |
| `python scripts/run_pytest.py` | `174 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

Ten new tests (164 → 174):

- **Supported layouts:** header, Vietnamese NFD name (extracted as NFC),
  two columns, a table cell, and a repeated email on two pages. Spans have
  boxes. A second extract is identical (deterministic).
- **Unsupported (5 cases):** encrypted, zero-page, 31 pages, image-only,
  malformed Stage-5 `%PDF-` stub.
- **Hidden content:** annotation + embedded file + JavaScript + sub-2 pt text
  → `REVIEW_REQUIRED` / `PDF_HIDDEN_CONTENT`. Alert `repr` contains no note
  text, attachment name, or script.
- **Validation service:** supported PDF → `QUEUED`; extracted email is present
  in memory and absent from logs; malformed PDF → `FAILED` / `PDF_MALFORMED`;
  DOCX is left `UPLOADED`.

All PDFs are generated at test time. None are committed (the file guard would
refuse PDF magic).

## Security/privacy review

- **No remote I/O.** PyMuPDF is local. `pytest-socket` still blocks sockets.
  Bind host remains `127.0.0.1`.
- **No extracted text in persistence or logs.** Validation logs document id,
  `passed`/`review`/`failed`, page count, and hidden-alert count only. Alerts
  are category/count/pages. SQLite schema is unchanged.
- **Parser errors are swallowed as codes.** MuPDF messages are disabled; exception
  text is not logged or returned.
- **Inputs are not overwritten.** Extract opens a copy from `InputStore`.
- **Test data** is synthetic. The agent never read, listed, or searched `data/`.

## Known limitations

- **Validation is not started from the API.** Documents stay `UPLOADED` after
  `start_batch` until Stage 12.
- **DOCX is out of scope** (Stage 6b). `ValidationService` refuses non-PDF.
- **Two-column reading order** is PyMuPDF's y-then-x word sort (best effort).
- **`PDF_TEXT_UNRELIABLE`** is implemented (FFFD / empty text objects) but has
  no dedicated generated fixture; image-only covers the empty-text path.
- **Resource limits** besides page count and the provisional xref cap wait for
  Stage 14.
- **Always-stripped items** (metadata, links, outlines) are not removed yet
  (Stage 10). They are not treated as hidden-content alerts.
- **PyMuPDF + pytest.** Use `make test` or `python scripts/run_pytest.py`.
  Direct `uv run pytest` can segfault on import or at process exit.
- **AGPL.** PoC-only until bank legal chooses AGPL or a commercial license.

## Manual verification steps

1. `make check` passes with 174 backend tests and the existing frontend tests.
2. Optional extract smoke test (synthetic bytes only):
   ```bash
   cd backend && uv run --locked python -c "
   from cv_masking.adapters.pdf import PyMuPDFExtractor
   from pathlib import Path
   # do not point this at a real CV
   "
   ```
   Prefer the unit tests; they generate the PDFs.

## Questions/decisions for the tech lead

None new. Hidden-content detection is owned by this stage as proposed in the
Stage 0 notes. Stage 12 should call `ValidationService.validate` for each
uploaded PDF after `start_batch`. Legal still needs to confirm PyMuPDF's
license path before any non-PoC distribution.

## Suggested commit message

```text
feat(pdf): validate and extract text-based PDFs (Stage 6)

- PyMuPDF adapter emits a format-neutral text model; no text is stored or logged
- Encrypted, empty, oversized, image-only, and hidden-content PDFs fail closed
- pytest must preload PyMuPDF (scripts/run_pytest.py) to avoid a 1.28 native crash
```
