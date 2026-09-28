# Stage 13 handoff — HR interface

## Stage and objective

Stage 13 is the first usable HR screen: a localhost React UI that uploads PDF
and DOCX CVs, shows per-document status, and downloads masked outputs. The
backend grows two endpoints the UI needs: an individual download and a
masked-only ZIP with a metadata CSV.

The UI polls. There are no WebSockets. Original filenames never leave the
browser tab. Extracted CV text is never rendered.

## Architecture decisions

- **Downloads stay on the existing stores.** `ExportService` reads completed
  or review-held outputs from `LocalOutputStore`. Download names are
  `redacted-<document-uuid>.<ext>` (D-38). A review-held file is downloadable
  so HR can inspect it before keep or delete (D-34).
- **ZIP is completed outputs only.** `GET /api/batches/{id}/export` writes
  `masked-<batch-uuid>.zip` in a work directory: each `COMPLETED` file plus
  `report.csv`. Review-held, failed, cancelled, and queued documents appear in
  the CSV only. The ZIP contains no inputs, work leftovers, or original names.
  Timestamps in the archive are the ZIP epoch `1980-01-01`. The work directory
  is closed in a FastAPI background task when the response finishes; the
  sweeper is the backstop if the process dies.
- **CSV is metadata only.** Columns: `document_id`, `status`, `error_code`,
  `count_<entity>` for every `EntityType`, `hidden_<category>` for every
  `HiddenContentCategory`. No filenames, hashes, paths, or values.
- **UI state.** React holds the current batch, local `File` objects, and a
  map from document id to display name. Language is the only
  `sessionStorage` key (`cv-masking-language`). Reloading the tab loses
  names; the table then shows `pdf`/`docx` or the first eight characters of
  the uuid.
- **Polling.** Every 1.5 s while the batch is `running` or any document is
  still in an active state. No WebSockets.
- **Salary is the only policy control.** The checkbox is on by default and
  can be changed on an open batch. Mandatory entity types have no UI.
- **Retry after start is a new batch.** Cancel/remove apply while the batch
  is `open`. After start, a failed document cannot be re-uploaded into the
  same batch (D-33). The UI tells HR to start a new batch. Retry while open
  deletes the document and uploads the `File` still in memory.
- **Vietnamese first.** Default language is `vi`. English is a toggle.
  `index.html` is `lang="vi"`. System fonts only; no remote assets.
- **Playwright Chromium is a `make install` download.** npm install scripts
  are disabled (`ignore-scripts=true`), so browsers are not fetched by
  `npm ci`. `make install` runs `npx playwright install chromium` after
  `npm ci`. `make test` / `make check` run Playwright after vitest.

## Files added/changed

| File | Change |
|---|---|
| `backend/src/cv_masking/application/exports.py` | `ExportService`, download and ZIP names |
| `backend/src/cv_masking/application/__init__.py` | Re-exports |
| `backend/src/cv_masking/api/runtime.py` | Wires `ExportService` |
| `backend/src/cv_masking/api/batches.py` | `has_output`; `GET .../download`; `GET .../export` |
| `backend/tests/api/test_downloads.py` | Download name/bytes; review-held; 409; ZIP/CSV |
| `backend/tests/api/test_document_actions.py` | View allowlist includes `has_output` |
| `backend/tests/application/service_helpers.py` | Optional `content=` to avoid hash clashes |
| `backend/tests/conftest.py` | Runtime includes exports |
| `frontend/src/{App,api,i18n,types,styles}.tsx/.ts/.css` | HR UI, API client, vi/en copy |
| `frontend/index.html` | `lang="vi"`, `referrer=no-referrer` |
| `frontend/tests/App.test.tsx` | Local-only, salary-only, names, partial failure |
| `frontend/tests/i18n.test.ts` | vi/en key parity |
| `frontend/playwright.config.ts`, `frontend/e2e/ui.spec.ts` | Loopback e2e |
| `frontend/package.json`, `frontend/package-lock.json` | `@playwright/test` ^1.63.0, `test:e2e` |
| `frontend/eslint.config.js`, `frontend/.prettierignore` | Ignore Playwright output |
| `Makefile` | Playwright Chromium on install; e2e in `test` |
| `.gitignore` | `playwright/.cache/` |
| `README.md`, `SECURITY.md`, `docs/error-codes.md`, `docs/data-retention.md`, `docs/stage-plan.md` | Stage 13 status and download/ZIP rules |
| `docs/stage-handoffs/stage-13.md` | This file |

## Dependencies (security and packaging impact)

| Package | Version | Scope | Notes |
|---|---|---|---|
| `@playwright/test` | ^1.63.0 (lockfile 1.63.0) | frontend dev | Apache-2.0. Test runner only. Does not ship in the production Vite bundle. `npx playwright install chromium` downloads Chrome for Testing, headless shell, and FFmpeg into `~/Library/Caches/ms-playwright` (about 280 MiB). No runtime network from the app. Video/trace/screenshot are off in the config. |

No new Python packages. No CDN, fonts, analytics, or WebSocket library.

## Commands run and exact results

- `npx playwright install chromium` (frontend): Chrome for Testing 153.0.8010.12
  (playwright chromium v1243), FFmpeg v1011, and Chrome Headless Shell, cached
  under `~/Library/Caches/ms-playwright`. Exit 0.
- `make fmt`: ruff 147 files unchanged; Prettier wrote `e2e/ui.spec.ts`,
  `eslint.config.js`, `tests/App.test.tsx`, `tests/i18n.test.ts`.
- `make check`:
  - file guard: 195 files checked, none refused;
  - `ruff format --check`: 147 files already formatted;
  - `ruff check`: all checks passed;
  - frontend Prettier + ESLint: pass;
  - `mypy --strict`: no issues in 145 source files;
  - `tsc --noEmit`: pass;
  - pytest: **689 passed** in 80 s;
  - vitest: 4 files, **11 passed**;
  - Playwright: **2 passed** in 10.8 s (chromium). The e2e webServer started
    the backend on `127.0.0.1:8765` and Vite on `127.0.0.1:5173`.

## Tests added

- **API downloads:** `redacted-<uuid>.pdf` Content-Disposition; `Cache-Control:
  no-store`; bytes match the stored output; a findings-review output can be
  downloaded; no-output is 409; ZIP holds only the completed file plus
  `report.csv` with counts and hidden kinds, no work leftovers, no names; wrong
  batch is 404.
- **Component:** default Vietnamese local-only + masked notice; English switch;
  salary is the only checkbox and is checked; mocked upload keeps
  `synthetic-mau.pdf` and does not render file bytes; a finished batch with one
  completed and one failed document shows both statuses, one download link, and
  the ZIP link.
- **i18n:** Vietnamese and English trees share the same keys.
- **Playwright:** the page is Vietnamese, local-only (any request not
  `127.0.0.1` / loopback WebSocket / `data:` / `about:blank` fails the test),
  salary is the only toggle; a synthetic PDF named `synthetic-cv.pdf` appears
  in the table and enables Start.

Existing `no-remote-urls` still scans `index.html`, `vite.config.ts`, and
`src/` and allows only `http://127.0.0.1`.

## Security/privacy review

- **No original filenames** in API responses, Content-Disposition, ZIP
  members, CSV, logs, or SQLite. Display names are React state only.
- **CSV and status** carry ids, states, codes, and counts. The download tests
  assert the synthetic marker `Nguyen` is absent from headers and the report.
- **ZIP** is completed outputs plus `report.csv`. Work directories are empty
  after the export test. Inputs are not added.
- **UI does not render extracted text.** Component tests assert the synthetic
  PDF payload is not in the document.
- **No remote assets.** `index.html` has no CDN; CSS uses system fonts;
  Playwright fails if the page requests a non-loopback URL.
- **Loopback bind unchanged.** Vite proxy `/api` → `http://127.0.0.1:8765`.
- **Playwright is dev-time.** It is not a runtime dependency. Browser binaries
  live in the user cache, not the repository.
- **Scope.** No Host/Origin token, CSRF, or rate limits (Stage 14). No
  launcher (Stage 15).

## Known limitations

- **Filenames vanish on reload.** There is no server-side name to restore.
- **Retry after start needs a new batch.** The started batch no longer accepts
  uploads.
- **ZIP omits review-held files.** HR can download a held file individually,
  keep it, then export again if they want it in the ZIP.
- **Hidden content is kind and count only.** Page numbers and part names are
  not persisted (Stage 12 / D-32 storage). The Stage 0 note mentioned page or
  part; the UI cannot show them without a new column.
- **SECURITY_* codes have no UI strings yet.** Stage 14. Unknown codes fall
  back to the code itself.
- **No CSRF or session token.** Download and ZIP are ordinary GET links on
  loopback (Stage 14).

## Manual verification steps

1. `make check`
2. `make dev`, open http://127.0.0.1:5173
3. Confirm the page is Vietnamese, the masked-not-anonymized notice, and a
   single salary checkbox that is on.
4. With **synthetic** PDF/DOCX only: drop files, watch progress, start, wait
   for statuses. Download `redacted-<uuid>.<ext>`. If any document completes,
   download the ZIP and confirm it has those files plus `report.csv` and no
   originals.
5. Switch to English; reload; names are gone, language stays English for the
   tab.

Do not use real CVs. Do not open `data/`.

## Questions/decisions for the tech lead

D-41 (Stage 12 queue choices) is already recorded as approved. Question 6
from Stage 12 (packaging / spawn in the Stage 15 launcher) is still open.

1. **ZIP membership.** Should a review-held output be included in the ZIP, or
   is “COMPLETED only” correct?
2. **Hidden locations.** Should kind/count remain enough, or should page/part
   be persisted so the UI can show them (Stage 0 note)?
3. **Reload.** Is losing display names on refresh acceptable for the PoC?

## Suggested commit message

`feat(ui): localhost HR interface with bilingual upload, polling, review, and masked downloads (Stage 13)`
