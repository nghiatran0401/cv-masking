# Stage 7 handoff — Deterministic detectors

## Stage and objective

Stage 7 detects pattern and labeled-field entities on the format-neutral text
model from Stages 6/6b. Detectors do not import PDF or DOCX adapters, do not
infer names, and do not redact. Processing is still not started from
`start_batch`; Stage 12 owns the worker.

## Architecture decisions

- **Port `ports/detection.py`.** `TextMatch` is a character range on one part
  (page or `part_name`), plus type, confidence, detector id/version. It never
  stores the matched text. `DocumentDetector.detect` consumes `ExtractedDocument`.
- **Adapter `adapters/detection`.** `PresidioDetector` uses Presidio
  `PatternRecognizer` for email, Vietnamese phone, and 12-digit CCCD. Labeled
  fields, CMND, passport, dates/age, salary, and URLs are custom rules on a
  diacritic-folded view that maps back to original offsets. `AnalyzerEngine` is
  never constructed, so no spaCy/transformer model is loaded or downloaded.
- **Application `DetectionService`.** Applies discard (< 0.50) and review
  (0.50–0.85) thresholds, builds `EntityFinding` (DOCX range, or PDF boxes from
  overlapping Stage 6 spans), and sets `DETECT_LOW_CONFIDENCE` when any kept
  finding needs review. Salary matches are always returned; `mask_salary` does
  not hide them.
- **Overlap.** `NATIONAL_ID` beats `PHONE`; `EMAIL` beats `PERSONAL_URL`; same
  type merges to the union span.
- **Reference sections.** Headings from masking-policy.md §3 open a region
  until the next experience/education/skills heading. Emails and phones there
  stay `EMAIL`/`PHONE` with detector ids `email.reference` / `phone.reference`.
- **False-positive controls.** 9-digit CMND, passport, DOB dates, and salary
  shapes require a nearby label. Isolated 12-digit CCCD is accepted
  (over-redaction). Names, family blocks, and unlabeled addresses are left to
  Stage 8.
- **Not wired into the HTTP API or `start_batch`.** Tests construct
  `DetectionService(PresidioDetector())` with hand-built `ExtractedDocument`s.

## New dependency: presidio-analyzer 2.2.364

| | |
|---|---|
| Purpose | Versioned `PatternRecognizer` / `RecognizerResult` API required by the Stage 7 prompt |
| License | MIT |
| Network | None in our path. Default `AnalyzerEngine` (spaCy model download) is not used. Built-in `EmailRecognizer` / `tldextract` fetches are not used. `pytest-socket` remains on. |
| Native code | Transitive `spacy` / `numpy` / `blis` wheels. We never load an NLP model. |
| Packaging | Large extra install (spaCy is a hard dependency of this Presidio version). No extra subprocess. Air-gapped after `uv sync --locked`. |

## Files added/changed

Added:
- `backend/src/cv_masking/ports/detection.py`
- `backend/src/cv_masking/adapters/detection/{__init__,normalize,detector}.py`
- `backend/src/cv_masking/application/detection.py`
- `backend/tests/application/{synthetic_detections,test_detect}.py`
- `docs/stage-handoffs/stage-7.md`

Changed:
- `backend/src/cv_masking/application/__init__.py`: export detection types
- `backend/tests/architecture/test_layer_boundaries.py`: detection must not import PDF/DOCX adapters
- `backend/pyproject.toml` / `uv.lock`: `presidio-analyzer==2.2.364`; mypy override
- Docs: `README.md`, `docs/stage-plan.md`

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `132 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `97 files already formatted` / `All checks passed!` |
| `npm run format:check`, `npm run lint` | pass |
| `mypy` (strict) | `Success: no issues found in 95 source files` |
| `python scripts/run_pytest.py` | `223 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

Thirty-six new backend tests (187 → 223):

- **Table-driven positives** (18 cases): each Stage 7 type, identified by entity
  name only.
- **False positives** (7 cases): work years, unlabeled CMND/passport/salary,
  skills, bare "Nam", city+year. Names and family types stay absent.
- **Overlap:** 12-digit id + mailto email; no phone.
- **Salary toggle:** same salary matches with `mask_salary` on or off.
- **Reference contacts:** detector ids `email.reference` / `phone.reference`.
- **No raw values** in `repr(findings/matches)` or logs.
- **PDF boxes** from overlapping Stage 6 spans.
- **Corpus P/R:** one synthetic CV snippet; precision and recall 1.0 per type
  (exact span match). Report is `(precision, recall)` numbers only.
- **Hypothesis:** reserved `*@example.test` / `example.invalid` emails and
  `09000000xx` mobiles; failure messages name the type, not the value.
- **Architecture:** detection adapter does not import PDF/DOCX adapters.

## Security/privacy review

- **No remote I/O.** Detectors run in-process. Sockets stay blocked in tests.
  Bind host remains `127.0.0.1`.
- **No matched text in findings or logs.** Logs are `findings=`, `suppressed=`,
  `review=` counts. `EntityFinding` still has no text field.
- **Test values** are the reserved synthetic set (example.test / example.invalid,
  `09000000xx`, `000000000012`, `000000003`, `A0000001`). Case ids are entity
  names, not values.
- **The agent never read, listed, or searched `data/`.**
- **Layering.** Application does not import Presidio. Detection does not import
  format adapters.

## Known limitations

- **Detection is not started from the API.** Stage 12 will call
  `DetectionService.detect` after validation.
- **PDF box mapping is overlap-only.** Fragmented tokens and ambiguous boxes
  stay Stage 9.
- **Name, family, and unlabeled contact-block addresses** are Stage 8.
- **Presidio pulls spaCy** as a package dependency even though no model is
  loaded. Bank legal already has the PyMuPDF AGPL question; spaCy is MIT/BSD
  but increases the wheel set.
- **Generic http URLs** need a contact label and may sit in the review band
  (0.70).

## Manual verification steps

1. `make check` passes with the new backend tests and the existing frontend tests.
2. Prefer the unit tests. Do not run the detector on a real CV.

## Questions/decisions for the tech lead

None new. Stage 12 should call `DetectionService` for each queued document.
Stage 8 owns names, family sections, and unlabeled header addresses.

## Suggested commit message

```text
feat(detect): add deterministic Stage 7 entity detectors

- Presidio pattern recognizers plus labeled-field rules; no spaCy models
- Salary is always emitted; raw values never enter findings, logs, or test names
```
