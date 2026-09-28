# Stage 16 handoff — Evaluation and release candidate

## Stage and objective

Stage 16 adds a synthetic evaluation harness and the release-candidate
documents. It does **not** add product features. Metrics are computed from
annotated fixtures generated at run time (policy-approved synthetic values).
Reports are metadata only. PDF and DOCX are scored separately. Photos and
images are recorded as unmasked (D-13). An authorized real-CV path exists
but is env-gated so Cursor/agents never run it (D-40).

## Architecture decisions

- **Composition root, not the API.** `cv_masking.evaluation` wires
  Presidio, PDF/DOCX extractors and redactors, and `DetectionService` in
  process. No FastAPI, SQLite, local stores, or writes under `data/`.
- **Fixtures at run time.** Annotated PDF (htmlbox + 16x16 image) and a
  minimal OOXML DOCX are built in memory. Malformed companions keep
  failure rate visible. Bytes are never committed (file guard).
- **Gold spans** are `str.find` of annotated values in extracted text,
  exact `(type, part, start, end)` match. Nested shorter spans (e.g.
  gender inside nationality) are dropped. Distinctive leaks: gold values
  of at least 6 characters still present in redacted bytes (D-37).
- **Authorized path.** Requires `CV_MASKING_AUTHORIZED_EVAL=1`. Skips
  symlinks and files over 21 MiB. Records operational counts only (no
  entity scores, no paths, no values).
- **Reproducibility.** `canonical_dict` drops `duration_ms`. Two
  synthetic runs match. Wall-clock duration is reported but not compared.
- **No policy change.** Confidence thresholds stay 0.85 / 0.50. D-28
  whole-word mapping was not re-measured as a usability score.
- **Intel** remains untested (same as Stage 15).

## Files added/changed

| File | Change |
|---|---|
| `backend/src/cv_masking/evaluation/` | Fixtures, metrics, harness, report, CLI |
| `backend/tests/evaluation/test_evaluation.py` | Reproducible metadata-only report; env gate |
| `backend/tests/architecture/test_layer_boundaries.py` | Evaluation must not import API/SQLite/storage |
| `Makefile` | `make eval` (synthetic only) |
| `docs/evaluation/README.md` | Harness + authorized human procedure |
| `docs/operator-guide.md` | HR operating instructions |
| `docs/troubleshooting.md` | Launcher and safe error codes |
| `docs/adr.md` | ADR-1–ADR-9 |
| `docs/demo-script.md` | Synthetic demo |
| `docs/release-checklist.md` | Go/no-go |
| `docs/stage-handoffs/stage-16.md` | This file |
| `README.md`, `SECURITY.md`, `THREAT_MODEL.md`, `docs/{stage-plan,install,data-retention,product-scope,masking-policy}.md` | Stage 16 / D-40 |

No new Python or npm packages.

## Commands run and exact results

- `uname -m`: **arm64** (Apple Silicon). Intel not tested.
- `make eval`: metadata JSON as tabulated below; no values or paths.
- `make check`:
  - file guard: 220 files checked, none refused;
  - ruff format/check: 165 files, all checks passed;
  - frontend Prettier + ESLint: pass;
  - `mypy --strict`: no issues in 163 source files;
  - `tsc --noEmit`: pass;
  - `make build`: Vite production bundle
    `index.html` 0.44 kB, CSS 1.15 kB, JS 241.90 kB gzip 76.53 kB;
  - pytest: **725 passed** in 79.69 s;
  - vitest: 5 files, **13 passed**;
  - Playwright: **2 passed** in 3.8 s.

## Tests added

- Synthetic JSON/Markdown/logs contain none of the policy sentinels.
- PDF and DOCX sections; `photos_and_images_unmasked`; malformed files
  yield `failed == 1` and `failure_rate == 0.5`; `leaked_distinctive == 0`.
- Two `canonical_dict` runs are equal; gender/ethnicity gold is 1 (nested
  nationality not double-counted).
- `run_authorized` without the env raises `PermissionError`; with the env
  on tmp synthetic files, the report has no paths or values and empty
  entity scores.
- CLI `--authorized` without the env is refused.
- Architecture: evaluation does not import `cv_masking.api`, sqlite, or
  local storage.

## Security/privacy review

- Synthetic values only; reports and tests never print them.
- Authorized evaluation cannot run unless a human sets the env var.
- Harness does not persist findings or open `data/`.
- Loopback, Host/Origin, session, and launcher are unchanged.
- No new network, CDN, telemetry, or subprocess.
- Residual: AGPL; unsigned launcher; photos unmasked; PDF Stage 8
  section misses on this htmlbox layout (see metrics below).

## Known limitations

- **One labeled CV per format.** Not a large corpus. Do not treat
  precision/recall as a production SLA.
- **PDF `family_details` and `reference_name` recall 0** on this fixture
  (Stage 8 layout heuristics vs htmlbox extraction). DOCX recall 1.0 for
  those types; the annotated DOCX still set `review_required`.
- **Short tokens** (`Nam`, `Kinh`) are excluded from the leak scan.
- **D-28** adjacent-word over-redaction was not scored.
- **Intel untested.**
- **AGPL / codesign** unchanged.

## Synthetic metrics (`make eval`, this checkout)

Policy version `1`. `photos_and_images_unmasked`: true. Distinctive leaks: 0.
Duration varies; counts below omit milliseconds.

### PDF (2 documents: 1 scored, 1 failed)

| entity | gold | pred | tp | fp | fn | precision | recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| candidate_name | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| date_of_birth | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| email | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| ethnicity | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| family_details | 1 | 0 | 0 | 0 | 1 | — | 0.0 |
| gender | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| health | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| marital_status | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| national_id | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 |
| nationality | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| passport | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| personal_url | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| phone | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| postal_address | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| reference_name | 1 | 0 | 0 | 0 | 1 | — | 0.0 |
| religion | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |
| salary | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 |

Failure rate 0.5 (malformed PDF). Review-required rate 0.0.

### DOCX (2 documents: 1 scored, 1 failed)

Every listed entity: gold=pred=tp (email and national_id gold 2; others 1);
fp=fn=0; precision and recall 1.0.

Failure rate 0.5 (malformed DOCX). Review-required rate 0.5 (the annotated
file was still scored).

## Manual verification steps

1. `make check`
2. `make eval` — confirm JSON has no person names, phones, or paths.
3. Optional: follow [docs/demo-script.md](../demo-script.md) with
   `/tmp/cv-masking-demo` synthetic files only.
4. Do **not** run `--authorized` from Cursor.

## Questions/decisions for the tech lead

1. **AGPL / IT install** (carried from Stage 15): when legal confirms, can
   this tree be copied to HR Macs?
2. **Intel smoke run** still outstanding.
3. **PDF Stage 8 misses** on htmlbox CVs: accept for the PoC, or add a
   later detector pass? (No change in this stage.)
4. **Confidence thresholds** were not recalibrated; confirm they stay.

## Suggested commit message

`feat(eval): add a synthetic metadata-only evaluation harness and release docs (Stage 16)`
