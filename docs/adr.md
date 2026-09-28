# Architecture decision records

Status: Stage 16 snapshot of decisions already recorded in
[product-scope.md](product-scope.md) §5, [AGENTS.md](../AGENTS.md), and
stage handoffs. Changing an ADR is a tech-lead decision.

## ADR-1 — Localhost-only runtime

**Context.** CVs must not leave the HR laptop.

**Decision.** Bind FastAPI to `127.0.0.1` only. No cloud, telemetry, remote
fonts, or external AI at runtime. Stage 14 adds Host/Origin, session, and
CSRF. Stage 15 serves the UI from the same origin.

**Consequence.** A second device cannot use the app. "Local" does not
protect against malware, browser extensions, backups, or Cursor.

## ADR-2 — Masking, not anonymization

**Context.** Hiring panels still need career history.

**Decision.** Redact the catalogue in [masking-policy.md](masking-policy.md).
Keep employers, schools, titles, skills, and dates (D-10). UI, README, and
reports must say the output is still personal data.

## ADR-3 — Format-neutral detection, native redaction

**Context.** HR receives PDF and Word CVs. Conversion would need Word or
LibreOffice and would mix formats.

**Decision.** One text model; detectors depend only on that model (D-17).
PDF is redacted with PyMuPDF apply-redactions; DOCX by removing XML text
(D-15, D-16). No `.doc`, no OCR, no format conversion.

## ADR-4 — Fail closed; verify before COMPLETED

**Context.** Overlay "redaction" leaks; uncertain detectors skip entities.

**Decision.** Uncertain cases become `REVIEW_REQUIRED` or `FAILED` (D-12).
`COMPLETED` only after an independent verifier reopens the output (Stages
11, 11b). Hidden content is always removed (D-32). Photos are not masked
(D-13).

## ADR-5 — Runtime files in ignored `data/`

**Context.** The app needs a cache for inputs, outputs, and SQLite.

**Decision.** Project `data/` with owner-only permissions, UUID names, no
filenames in metadata (D-22–D-25). No age expiry of stored CVs (D-23).
Agents never read `data/`.

## ADR-6 — One worker process

**Context.** A 50-file batch must not freeze the UI or fork a process per
file.

**Decision.** One `spawn` worker, one document at a time, 120 s budget by
killing the process (D-33, D-41). Queue is persisted document states.

## ADR-7 — Unsigned macOS launcher, uv venv

**Context.** HR needs one command; Stage 12 spawn needs a real interpreter.

**Decision.** `scripts/cv-masking.command` plus `backend/.venv`, not a
frozen binary. Unsigned, not notarized (D-39, D-42). PyMuPDF AGPL-3.0 or
commercial remains for bank legal. Apple Silicon tested; Intel not tested.

## ADR-8 — Synthetic evaluation; authorized run optional

**Context.** Release evidence must not put real CVs in git or Cursor.

**Decision.** Stage 16 generates annotated fixtures at run time and prints
metadata-only metrics, PDF and DOCX separately (D-40). An authorized
directory run requires `CV_MASKING_AUTHORIZED_EVAL=1`, records no gold
scores, and is never executed by agents on real files.

## ADR-9 — No new product features in Stage 16

**Context.** The stage is evidence and documentation for a go/no-go.

**Decision.** The harness composes existing adapters. Confidence
thresholds, mapping over-redaction (D-28), and Windows stay unchanged.
