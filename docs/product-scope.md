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
- Batch processing: up to 50 files per batch (D-30), one job per document, one local background worker process handling one document at a time (D-33).
- Detection of the entity catalogue in [masking-policy.md](masking-policy.md).
- Permanent redaction using PDF redaction APIs (redaction annotations + apply), never overlays.
- Independent verification of every output before it can be `COMPLETED`.
- Hidden-content removal: hidden/non-visible content is always removed, and HR sees the
  *kind* and count of what was removed (D-32; see [supported-pdf.md](supported-pdf.md) §4).
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
| D-05 | **Superseded by D-32.** Hidden content → alert HR with kind/count/page of content found; HR approves or denies the CV. On approve, the flagged content is removed from the output (never preserved). | Tech lead, Stage 0 (removal-on-approve is an agent assumption, see Q-02) |
| D-06 | ~~Retention: outputs kept until HR clears them or 24 h, whichever is first;~~ inputs deleted as soon as the job reaches a terminal state. The 24 h part is superseded by D-23. | Tech lead, Stage 0 |
| D-07 | Output name `redacted-<uuid>.pdf`; for DOCX input, `redacted-<uuid>.docx`. | Tech lead, Stage 0 (revised) |
| D-08 | PoC platform is macOS only. Windows gets its own stage later; no current stage carries Windows requirements. | Tech lead, Stage 0 (revised) |
| D-09 | Limits: 20 MB per file, 30 pages per file, ~~100~~ 50 files per batch (D-30) (configurable, cannot be raised above hard caps without code change). | Tech lead, Stage 0 |
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
| D-25 | Purging a batch deletes its files and then every metadata row about it (batch, documents, hashes, counts, codes); nothing is kept as a tombstone. Job metadata lives in `data/metadata/jobs.sqlite3`. | Tech lead, Stage 4 |
| D-26 | File/metadata reconciliation (remove files no document needs, and unreferenced files older than 1 h) is built in Stage 4 as a service call; Stage 12 schedules it. | Tech lead, Stage 4 |
| D-27 | **Superseded by D-32** (no hidden-content approval exists). If HR approves a hidden-content review in a FINISHED batch, the batch returns to RUNNING and finishes again once that document is settled. Implemented in Stage 12. | Tech lead, after Stage 4 |
| D-28 | PDF mapping redacts a partly covered word whole (trailing punctuation, a label glued to its value). Accepted for the PoC because it only over-redacts; per-character boxes are not built. Revisit only if Stage 16 evaluation shows it harms usability. | Tech lead, after Stage 9 |
| D-29 | **Revised by D-32/D-34:** the hidden-content approval parts no longer apply; Stage 12 keeps the findings review backend. The hidden-content approve/deny flow is owned per stage: Stage 6/6b detect and alert (done); Stage 10/10b remove each approved category and test the removal; Stage 11/11b verify no category remains; Stage 12 owns the backend (approve/deny service and API endpoints for both hidden-content and findings reviews, the `REVIEW_REQUIRED → QUEUED` re-run, deleting the output on deny, and D-27); Stage 13 owns the screen. Resolves the §6 gap. | Tech lead, after Stage 9 |
| D-30 | The batch cap is lowered from 100 to 50 files to keep the PoC simple; HR runs several batches for more CVs. The SQLite `document_count` check (0–100, Stage 4 migration) is left as a looser backstop; the domain enforces 50. | Tech lead, after Stage 10 |
| D-31 | Stage 10 follow-ups: `REDACT_SANITIZE_FAILED` is terminal (every cause is deterministic); PDF tagged structure (`StructTreeRoot`, `MarkInfo`, `StructParent(s)`) and `PieceInfo` are always stripped (they can hold text not on the page; accessibility tags are lost); `MAP_AMBIGUOUS` counts only types the policy redacts; label text is light grey (0.9) on black. | Tech lead, after Stage 10 |
| D-32 | Hidden content (every PDF §4 and DOCX §6.4 category) is always removed, with no HR approve/deny step. HR sees the kind and count removed in the status and report. Stricter on privacy (nothing hidden is ever kept) and removes the approval flow, the re-run, and reopening finished batches. Stage 12 removes the hidden-content review path from the extractors, domain state machine, and jobs, and always calls the redactor with removal on. Supersedes D-05 and D-27; revises D-29. | Tech lead, after Stage 10 |
| D-33 | Stage 12 runs one background worker process that handles one document at a time (no worker pool). The per-document time limit is enforced by ending that process. After a crash or restart, documents left mid-processing are marked failed with the retryable `JOB_INTERRUPTED`; HR retries them. Only queued documents can be cancelled. | Tech lead, after Stage 10 |
| D-34 | Findings review is one step: HR opens the verified masked file and either keeps it (approve → `COMPLETED`) or deletes it (deny → `REJECTED`, output deleted). No re-run and no editing of findings. Verifier `REVIEW_REQUIRED` stays deny-only. | Tech lead, after Stage 10 |
| D-35 | DOCX text inside legacy `w:object` content (OLE objects, old drawings) is not redacted in place. The object is always removed (§6.4), and a finding inside it makes the redactor fail closed (`REDACT_SANITIZE_FAILED`/`REDACT_FAILED`), so HR redacts that CV by hand. Revisit only if pilot users hit it often; the fix would be to treat a range entirely inside a deleted element as handled. | Tech lead, after Stage 10b |
| D-36 | Hidden text applied through a style is not resolved by the redactor. Such text is still extracted and scanned, so PII in it is redacted. Stage 11b rejects the output (`VERIFY_RESIDUAL_METADATA`) if any style in `styles.xml` sets `w:vanish` or `w:specVanish` and the document uses that style. | Tech lead, after Stage 10b |
| D-37 | Verification (Stages 11, 11b) reruns only the deterministic Stage 7 rules; names are verified by the source-value search and the position check. Only distinctive source values (multi-token names, contacts, identifiers, full dates of birth, numbered addresses; at least 6 letters or digits) are searched anywhere in the output; short or generic values are checked only where they were redacted and by the rerun. An uncertain residual detection gives a deny-only `REVIEW_REQUIRED` (`VERIFY_REVIEW`), not `FAILED`. | Tech lead, after Stage 11 |
| D-38 | Downloads are named `redacted-<uuid>.pdf/.docx`; original file names (which often contain the candidate's name) are never used for outputs. The UI shows the original name next to each row from browser memory only. The ZIP holds one metadata-only CSV report: document id, status, error code, count per entity type, and hidden-content kinds/counts removed. No file names and no values. | Tech lead, after Stage 11 |
| D-39 | Stage 15 launcher is a double-clickable `.command` script with a bundled Python environment, installed once by IT; no signing or notarization in the PoC. Before Stage 15 the tech lead confirms the PyMuPDF AGPL-3.0 licence with bank legal/IT. | Tech lead, after Stage 11 |
| D-40 | Stage 16 evaluation uses a synthetic annotated set kept in the repository. Optionally, HR may later run the harness locally on authorized real CVs and share only the metadata report; real CVs never go through Cursor or any AI tool. | Tech lead, after Stage 11 |
| D-41 | Stage 12 choices: `DETECT_FAILED` and `JOB_TIMEOUT` are terminal (`T`), because detection is deterministic and a retry is a fresh upload that would fail the same way; the per-document budget is 120 s (configurable, cap 600 s) covering validation, processing, and verification; cancel applies to `CREATED`, `UPLOADED`, and `QUEUED`; at shutdown the document in progress gets 10 s, then fails with `JOB_INTERRUPTED`; documents a Stage 11 database held for hidden-content approval fail with `JOB_INTERRUPTED` on upgrade (migration 2). | Tech lead, after Stage 12 |
| D-42 | Stage 15 launcher: uv virtualenv (not a frozen binary) so worker `spawn` is unchanged; `--desktop` takes an exclusive flock, generates a one-time bootstrap query that seeds the Stage 14 session/CSRF, and opens the default browser with `/usr/bin/open`; `GET /api/health` stays unauthenticated; AGPL remains residual until legal confirms; Apple Silicon is tested, Intel is documented untested. | Tech lead, Stage 15 |

## 6. Known gaps between approved scope and the stage plan

These are recorded, not resolved. Each is a question for the tech lead in the Stage 0 handoff.

None open.

Resolved: detector coverage (D-14), photos (D-13, accepted risk), Windows (D-08, future
stage), DOCX (D-15 to D-17), hidden-content approve/deny ownership (D-29).
