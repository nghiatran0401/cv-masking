# Stage 5 handoff — Batch upload API

## Stage and objective

Stage 5 receives CVs into an OPEN batch, one multipart request per file. The API can
create a batch, upload a PDF or DOCX, report status, remove a document, purge a batch,
and start the batch. Files are streamed in 64 KiB chunks, identified by content only,
and stored under random paths. There is still no PDF or DOCX content parsing and no
masking. Starting a batch moves it to RUNNING; documents stay UPLOADED until Stage 6.

## Architecture decisions

- **Application, not API, owns the rules.** `UploadLimits` lives in
  `application/uploads.py`. The API maps `Settings` to those limits. The application
  layer does not import FastAPI, `cv_masking.config`, or `sqlite3`.
- **`create_app(runtime=None)` stays side-effect free.** Health tests construct an app
  without opening `data/`. Production uses `create_runtime_app()` → `build_runtime()`,
  which is what `python -m cv_masking` loads.
- **Identify by content, then check the declaration.**
  - PDF: `%PDF-` anywhere in the first 1024 bytes.
  - OLE / legacy `.doc` / encrypted Office: magic `d0cf11e0…` → `UPLOAD_UNSUPPORTED_TYPE`.
  - ZIP: read only `[Content_Types].xml` (capped at 1 MiB) and string-search it. No XML
    parser (avoids XXE). `macroEnabled`, `vbaProject`, or template markers →
    `DOCX_MACRO_OR_TEMPLATE`. The Word main document type → DOCX. Anything else →
    unsupported.
  - A `.doc` / `.docm` / `.dotx` / `.dotm` extension, or a content type that disagrees
    with the identified kind, is `UPLOAD_SPOOFED_TYPE`.
  - The original filename is used only for that check and is then discarded. It is
    never stored, logged, or returned.
- **Stream, do not buffer.** The request body is read 64 KiB at a time onto
  `data/work/<uuid>/upload.bin`. After identification, `InputStore.save_stream` reads
  the same file in 64 KiB chunks. The whole upload is never held in memory.
- **Failed uploads become FAILED rows.** A document row is added first so the file-count
  limit stays consistent under concurrency. A refused or timed-out upload is
  `reject_upload`'d. Those rows count toward the file limit, not the byte total (they
  have no `size_bytes`). One bad file does not delete or change any other document.
- **Duplicates are same-batch content hash only.** A second copy is deleted from
  `inputs/` and the new row is FAILED with `UPLOAD_DUPLICATE`.
- **Start is `start_batch` only.** No fake validation. Documents remain UPLOADED.
- **Limits** (env vars can lower these, never raise them):
  - `CV_MASKING_MAX_FILE_BYTES` — default / hard cap 20 MiB
  - `CV_MASKING_MAX_FILES_PER_BATCH` — default / hard cap 100
  - `CV_MASKING_MAX_BATCH_BYTES` — default / hard cap 500 MiB (Q-06)
  - `CV_MASKING_UPLOAD_TIMEOUT_SECONDS` — default 60, hard cap 15 minutes
- **HTTP mapping** is in [error-codes.md](../error-codes.md) §4. Unknown IDs return
  `404` with `INTERNAL_ERROR` (there is no `NOT_FOUND` code). Validation failures
  from FastAPI become `UPLOAD_MALFORMED_REQUEST` with no pydantic detail echoed.
- **New dependency: `python-multipart==0.0.32`.** FastAPI needs it to parse
  `multipart/form-data` for `UploadFile`. License Apache-2.0. Pure Python, no native
  code, no network calls, no subprocess. Packaging impact is one small wheel already
  locked in `backend/uv.lock`.

## Files added/changed

Added:
- `backend/src/cv_masking/application/{identify,uploads}.py`
- `backend/src/cv_masking/api/{batches,errors,runtime}.py`
- `backend/tests/application/{synthetic_files,test_identify,test_upload_service}.py`
- `backend/tests/api/test_uploads.py`
- `docs/stage-handoffs/stage-5.md`

Changed:
- `backend/src/cv_masking/domain/limits.py`: batch-byte and timeout caps; `READ_CHUNK_BYTES`.
- `backend/src/cv_masking/config.py`: four lowerable upload settings.
- `backend/src/cv_masking/application/__init__.py`: export identify + upload types.
- `backend/src/cv_masking/api/app.py`: register batch routes and closed error handlers.
- `backend/src/cv_masking/__main__.py`: factory is `create_runtime_app`.
- `backend/pyproject.toml` / `uv.lock`: `python-multipart>=0.0.32`.
- Tests: `conftest.py` (uploads/runtime/client fixtures), `test_config.py`,
  `test_entrypoint.py`, `test_no_pii_persisted.py` (log-word allowlist).
- Docs: `README.md`, `docs/stage-plan.md` (Stages 4 and 5 complete),
  `docs/data-retention.md` (work area used for upload sniffing),
  `docs/error-codes.md` §4 HTTP mapping.

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `107 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `77 files already formatted` / `All checks passed!` |
| `npm run format:check`, `npm run lint` | pass |
| `mypy` (strict) | `Success: no issues found in 76 source files` |
| `pytest` | `164 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

Fourteen new tests on top of the Stage 4 suite (150 → 164):

- **Identify (2):** PDF, DOCX, macro-enabled DOCX, and OLE/`.doc` magic; spoofed
  extension or content type is detected; a missing declaration is not treated as a spoof.
- **Upload service (2):** a clock that advances past the timeout refuses the upload and
  leaves a FAILED row; an unknown batch is `RecordNotFoundError`.
- **API (9):**
  - PDF + DOCX upload, then start (documents stay uploaded; two input objects exist);
  - spoofed `.docx` extension on a PDF is 400 and stores nothing;
  - a file over the configured per-file cap is 413 and stores nothing;
  - a second copy of the same bytes in the same batch is 409 and leaves one input;
  - a request with no file part is 400 `UPLOAD_MALFORMED_REQUEST`;
  - one unsupported file does not remove the good upload (FAILED + UPLOADED);
  - a filename containing a synthetic Vietnamese name and phone never appears in the
    JSON status or in `cv_masking` logs;
  - a started batch rejects further uploads with `UPLOAD_BATCH_CLOSED`;
  - purge deletes the batch, its documents, and the stored inputs.
- **Config (1 extra assertion):** `CV_MASKING_MAX_FILE_BYTES` cannot exceed the hard cap.

## Security/privacy review

- **No remote I/O.** `python-multipart` is local parsing only. Bind host remains
  `127.0.0.1` with no override. `pytest-socket` still blocks network in tests.
  Interactive docs stay disabled (they would load a CDN).
- **Filename never leaves the upload handler.** Extension is extracted and the rest of
  the name is dropped. Status views have no `filename` or `sha256` field. Logs record
  document id, format, byte count, and error code only.
- **No raw PII in persistence.** Upload does not write text, names, or hashes to the
  API response. The SHA-256 stays in SQLite as before (Stage 4) and is never logged.
- **Fail closed.** Macro/template, OLE, spoof, empty, oversized, duplicate, closed
  batch, and timeout all become safe codes. FastAPI validation errors do not echo
  request fields.
- **Work files are temporary.** Identification uses `WorkArea.attempt()`, which deletes
  the directory on the way out. A refused upload never remains in `inputs/`.
- **Test data.** All fixtures are synthetic (`%PDF-1.7` and a generated DOCX ZIP). The
  agent never read, listed, or searched `data/`.

## Known limitations

- **No content parsing.** A file that starts with `%PDF-` or looks like a DOCX is
  accepted even if it would fail Stage 6 / 6b validation (encrypted PDF, image-only,
  empty body, zip bombs beyond the Content_Types cap, and so on). Encrypted DOCX
  looks like OLE and is already refused here as unsupported.
- **Start does not validate.** Documents remain UPLOADED. Stage 6 owns
  `start_validation`.
- **Concurrent identical uploads** in the same batch can both succeed if they pass the
  hash check before either row is recorded. The API is one file per request; there is
  no unique `(batch_id, sha256)` constraint.
- **FAILED upload rows count toward the file limit** until HR removes them or purges
  the batch.
- **Request timeout is application-level**, measured by the injected clock while
  chunks arrive. It is not a socket-level idle timeout (Stage 14).
- **Starlette may spool a large multipart body to a temp file** before our handler
  runs. That is a browser/ASGI copy, not an application store, and is already noted
  in data-retention.md.

## Manual verification steps

1. `make check` passes with 164 backend tests and the existing frontend tests.
2. Optional smoke test against a throwaway process (synthetic file only):
   ```bash
   cd backend && uv run --locked python -m cv_masking
   # in another terminal:
   curl -sS -X POST http://127.0.0.1:8765/api/batches -H 'content-type: application/json' -d '{}'
   printf '%%PDF-1.7\n%% synthetic\n' > /tmp/synthetic.pdf
   curl -sS -F file=@/tmp/synthetic.pdf http://127.0.0.1:8765/api/batches/<batch_id>/documents
   ```
   Expect `201` with `state=uploaded`, `document_format=pdf`, and no `filename` field.
   Then `rm /tmp/synthetic.pdf`. Do not point curl at a real CV.
3. Confirm `lsof` / the banner shows `127.0.0.1:8765`, not `0.0.0.0`.

## Questions/decisions for the tech lead

None new. Earlier Stage 5 choices still stand: failed uploads become FAILED rows;
duplicates are same-batch hash only; start does not fake validation; encrypted DOCX
is unsupported at upload; Q-06 500 MiB hard cap.

## Suggested commit message

```text
feat(api): batch upload API for PDF and DOCX (Stage 5)

- Stream one file per request; identify by content; reject macros, .doc, spoofs
- Configurable count/size/timeout caps that cannot exceed the hard limits
- Never persist or log the source filename; one bad file does not touch others
- python-multipart 0.0.32 for local multipart parsing only
```
