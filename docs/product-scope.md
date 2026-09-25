# Product scope

Status: Stage 0 baseline. Changes require tech-lead approval and an update to the
decision log below.

## 1. Problem

HR staff at the bank receive candidate CVs and need to share them with hiring
panels without exposing personal identifiers or sensitive attributes. Manual
blacking-out is slow, inconsistent, and often only visual (the text remains
extractable underneath). This PoC batch-processes CVs on the HR user's own
laptop and produces permanently redacted copies.

## 2. Users and roles

| Role | Description |
|---|---|
| HR user | Uploads CVs, chooses the salary toggle, reviews alerts, approves/denies documents flagged for review, downloads masked outputs. |
| Admin | In this PoC the admin is the same local HR user. There is no multi-user access control, no login, and no remote admin console. "Alert to admin/HR" means the alert appears in the local UI. |
| Developer | Builds and tests the app using synthetic data only. Never receives real CVs. |

## 3. In scope (PoC)

- Localhost-only web app: FastAPI backend bound to `127.0.0.1`, React UI served from the same origin.
- Platform: **macOS** (Apple Silicon development laptop) for the PoC. Windows is a
  planned future stage (D-08) and is not supported until that stage is delivered.
- Input: text-based **PDF** and Word **DOCX** CVs. Languages: **Vietnamese (primary) and
  English**, including bilingual CVs.
- Shared pipeline: each format is validated and extracted into one format-neutral text
  model; detection is shared; redaction and verification are format-specific and happen in
  the original format (D-15, D-16).
- Batch processing: up to 100 files per batch, one job per document, bounded local worker pool.
- Detection of the entity catalogue in [masking-policy.md](masking-policy.md).
- Permanent redaction using PDF redaction APIs (redaction annotations + apply), never overlays.
- Independent verification of every output before it can be `COMPLETED`.
- Hidden-content alerts: documents containing hidden/non-visible content are held for HR
  review with a description of the *kind* of content found (see [supported-pdf.md](supported-pdf.md) §4).
- Per-document status, safe finding counts (counts per entity type only), individual download,
  masked-only ZIP, and a metadata-only CSV report.
- Output file naming: `redacted-<uuid>.pdf` for PDF input, `redacted-<uuid>.docx` for DOCX
  input. Original filenames are held in browser memory only.
- Local retention and cleanup per [data-retention.md](data-retention.md).

## 4. Non-goals

- **Not anonymization.** Output is *masked*, not anonymous. Employers, schools, job titles,
  dates, project names, and writing style can still re-identify a candidate. The UI and
  README must say this.
- No cloud, AWS, remote storage, telemetry, analytics, crash reporting, update checks,
  remote fonts/CDNs, or external AI/LLM/API calls at runtime.
- No OCR and no image/scanned CVs in this PoC. Image-only PDFs go to `REVIEW_REQUIRED`
  with no output (see [supported-pdf.md](supported-pdf.md)).
- No photo or image masking. Embedded images, including candidate photos and any text
  inside images, pass through to the output unchanged (D-13).
- No Windows support until its dedicated future stage.
- No editing of the original document; inputs are never overwritten.
- No format conversion: a PDF is never turned into a DOCX or vice versa, and no
  LibreOffice or Word automation is used.
- No legacy `.doc`, `.rtf`, `.odt`, macro-enabled `.docm`, or Word templates.
- No display of extracted CV text in the UI, logs, API responses, or reports.
- No multi-user server, LAN sharing, or remote access. A second device must not be able to connect.
- No guarantee against a compromised laptop (malware, admin-level attacker). See [THREAT_MODEL.md](../THREAT_MODEL.md).
- No long-term archive or audit trail of processed CVs (see decision D-11).
- Not a hiring decision tool; no scoring, ranking, or summarization.

## 5. Decision log

| ID | Decision | Source |
|---|---|---|
| D-01 | Runtime data never leaves the laptop; bind `127.0.0.1` only. | AGENTS.md |
| D-02 | Mandatory entity list per masking-policy.md §2; salary is an HR-selectable toggle, default **ON** (masked). | Tech lead, Stage 0 |
| D-03 | Vietnamese is the primary language; English and bilingual CVs are supported. | Tech lead, Stage 0 |
| D-04 | No image CVs in this phase. | Tech lead, Stage 0 |
| D-05 | Hidden content → alert HR with kind/count/page of content found; HR approves or denies the CV. On approve, the flagged content is removed from the output (never preserved). | Tech lead, Stage 0 (removal-on-approve is an agent assumption, see Q-02) |
| D-06 | ~~Retention: outputs kept until HR clears them or 24 h, whichever is first;~~ inputs deleted as soon as the job reaches a terminal state. The 24 h part is superseded by D-23. | Tech lead, Stage 0 |
| D-07 | Output name `redacted-<uuid>.pdf`; for DOCX input, `redacted-<uuid>.docx`. | Tech lead, Stage 0 (revised) |
| D-08 | PoC platform is macOS only. Windows gets its own stage later; no current stage carries Windows requirements. | Tech lead, Stage 0 (revised) |
| D-09 | Limits: 20 MB per file, 30 pages per file, 100 files per batch (configurable, cannot be raised above hard caps without code change). | Tech lead, Stage 0 |
| D-10 | Masking is not anonymization; keep employers, schools, job titles, skills, dates. | Tech lead, Stage 0 |
| D-11 | Job metadata (SQLite) is purged together with the batch; no long-term audit log in the PoC. | Agent default, see Q-05 |
| D-12 | When uncertain, fail closed: `REVIEW_REQUIRED` or `FAILED`, never `COMPLETED`. | AGENTS.md |
| D-13 | No image removal and no OCR in the PoC. Candidate photos are **not** masked; this is an accepted residual risk that the UI, README, and reports must disclose. | Tech lead, Stage 0 (revised) |
| D-14 | Detectors for passport, date of birth/age, gender, marital status, nationality, religion, ethnicity, health, personal URLs, and labeled addresses are added to Stage 7; family-details sections and unlabeled contact-block addresses are added to Stage 8. | Tech lead, Stage 0 |
| D-15 | DOCX is supported by redacting the DOCX directly and returning a DOCX. No conversion to or from PDF. | Tech lead, Stage 0 |
| D-16 | DOCX work is added as Stages 6b (validate + extract), 10b (redact), and 11b (verify), placed right after their PDF counterparts. | Tech lead, Stage 0 |
| D-17 | The Stage 2 domain model is format-neutral from the start: a `DocumentFormat` (PDF, DOCX) and a finding location that is either PDF page + boxes or DOCX part + character range. | Tech lead, Stage 0 |
| D-18 | Every stage ends with a git commit after all checks pass. | Tech lead, Stage 0 |
| D-19 | ~~A document still in review 24 h after upload fails with the terminal code `JOB_EXPIRED`.~~ Superseded by D-23: documents stay in review until HR decides; `JOB_EXPIRED` is removed. | Tech lead, Stage 2 |
| D-20 | A failed verification shows HR its most serious code: residual finding, residual detection, residual metadata, invalid output, page-count mismatch, structure mismatch. | Tech lead, Stage 2 |
| D-21 | A pre-commit and `make check` file guard refuses document, image, data, and log files (by name and content) and files over 1 MiB, except synthetic fixtures. npm install scripts are disabled. | Tech lead, Stage 2 follow-up |
| D-22 | Runtime files live in `<project>/data/`, inside the checkout, ignored by `.gitignore` and `.cursorignore` and refused by the file guard. The tech lead accepted the residual risks: Cursor/AI tooling working in the same folder, and Time Machine backing it up unless excluded by hand. Supersedes the "outside the repository" rule. | Tech lead, Stage 3 follow-up |
| D-23 | No automatic deletion of stored inputs and outputs by age; HR deletes them manually. The app still deletes work files after every attempt, and the sweeper removes crash leftovers (temp files, work directories, unexpected entries) after 1 h. | Tech lead, Stage 3 follow-up |
| D-24 | Quitting the app does not erase inputs, outputs, or metadata (answers Q-07). | Tech lead, Stage 3 follow-up |

## 6. Known gaps between approved scope and the stage plan

These are recorded, not resolved. Each is a question for the tech lead in the Stage 0 handoff.

| Gap | Impact | Interim policy until resolved |
|---|---|---|
| **Hidden-content approve/deny** workflow is not in Stages 6, 10, 11, or 13. | Review flow has no owner stage. | Detection belongs to Stage 6, removal to Stage 10, verification to Stage 11, UI to Stage 13. |

Resolved: detector coverage (D-14), photos (D-13, accepted risk), Windows (D-08, future
stage), DOCX (D-15 to D-17).
