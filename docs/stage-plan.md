# Stage plan

Source: tech lead, Stage 0. Stage prompts for 0–16 are recorded verbatim.
Stages 6b, 10b, and 11b were drafted by the agent and approved in principle by the
tech lead (D-16); their wording may be refined when each stage is requested.
"Stage 0 notes" record how Stage 0 decisions (see [product-scope.md](product-scope.md) §5)
apply to each stage; "approved scope addition" marks notes the tech lead approved.
Each stage is executed only when explicitly requested: plan first, then implement,
then handoff, then **git commit** (D-18).

| # | Name | Status |
|---|---|---|
| 0 | Governance and threat model | Complete (committed) |
| 1 | Repository and quality gates | Complete (committed) |
| 2 | Domain model and state machine | Complete (committed) |
| 3 | Local storage and cleanup | Complete (committed) |
| 4 | SQLite metadata | Complete (committed) |
| 5 | Batch upload API | Complete (committed) |
| 6 | PDF validation and extraction | Complete (committed) |
| 6b | DOCX validation and extraction | Complete (committed) |
| 7 | Deterministic detectors | Complete (committed) |
| 8 | Candidate and reference names | Complete (committed) |
| 9 | Span-to-box mapping | Complete (committed) |
| 10 | Permanent redaction | Complete (committed) |
| 10b | DOCX redaction | Not started |
| 11 | Independent verification | Not started |
| 11b | DOCX verification | Not started |
| 12 | Local job queue | Not started |
| 13 | HR interface | Not started |
| 14 | Runtime hardening | Not started |
| 15 | Local build and launcher | Not started |
| 16 | Evaluation and release candidate | Not started |
| — | Windows support (future, unscheduled) | Not defined |

---

## Stage 0 — Governance and threat model
Goal: Establish constraints before code exists.

```text
Execute Stage 0 only. Create planning documentation, not application code. Define product scope, non-goals, entities and policies, data-flow diagram, trust boundaries, threat model, privacy assumptions, local retention/cleanup policy, supported PDF definition, safe error-code taxonomy, and stage plan. Create .gitignore, .cursorignore, AGENTS.md, SECURITY.md, THREAT_MODEL.md, and docs/masking-policy.md. Use synthetic examples only. Stop after the handoff.
```

Tech-lead lesson: Understand what "local" protects and what it does not. Browser uploads still create temporary application copies, Cursor prompts still leave the machine for inference, and masking is not equivalent to guaranteed anonymization.

Acceptance: No application code; scope and security decisions are explicit; ignore rules cover all runtime data; no real data exists in the repository.

## Stage 1 — Repository and quality gates
Goal: Establish reproducible Python/TypeScript development.

```text
Execute Stage 1 only. Scaffold backend and frontend according to the approved architecture. Configure Python 3.12, uv or Poetry, FastAPI, pytest, Ruff, MyPy, React, Vite, TypeScript, Vitest, ESLint, Prettier, and common Makefile commands. Add health endpoint and minimal static page only. Bind development backend to 127.0.0.1. Add no file upload or PII logic. Stop after tests and handoff.
```

Acceptance: One command starts development; health test passes; frontend test passes; lint/type-check pass; no remote assets or runtime network calls.

Stage 0 notes: macOS only (D-08). `.gitignore` ignores `*.png`; any frontend image asset needs an explicit, reviewed exception.

## Stage 2 — Domain model and state machine
Goal: Define behavior before infrastructure.

```text
Execute Stage 2 only. Implement typed domain entities for Batch, DocumentJob, MaskingPolicy, EntityFinding, BoundingBox, VerificationResult, safe ErrorCode, and validated state transitions. Mandatory masks cannot be disabled; salary is configurable. Add exhaustive unit tests for valid/invalid transitions and policy validation. No database, upload, PDF parsing, or UI work.
```

Acceptance: Domain has no FastAPI/filesystem/SQLAlchemy imports; invalid state transitions fail; raw PII has no persistent model field.

Stage 0 notes: State machine baseline in [error-codes.md](error-codes.md) §2, including `REJECTED` (HR denied) and the hidden-content approve/deny transition. **Approved scope addition (D-17):** the model is format-neutral — `DocumentFormat` (PDF, DOCX), and `EntityFinding` location is a discriminated union of PDF location (page + one or more `BoundingBox`) and DOCX location (part + character range). DOCX error codes are in error-codes.md.

## Stage 3 — Local storage and cleanup
Goal: Safely manage temporary files without CV logic.

```text
Execute Stage 3 only. Implement LocalInputStore and LocalOutputStore behind ports. Use randomized IDs and paths beneath an application cache root outside the repository. Enforce owner-only permissions where supported, path containment, atomic writes, streamed SHA-256 calculation, cleanup after success/failure, and orphan cleanup by age. Add adversarial path-traversal and symlink tests. Never use original filenames in server paths.
```

Acceptance: Inputs cannot escape cache root; interrupted writes do not appear complete; cleanup tests pass; logs contain random IDs only.

Stage 0 notes: macOS POSIX permissions only (D-08). Retention windows in [data-retention.md](data-retention.md) §4. Stores handle both `.pdf` and `.docx` objects; the extension comes from the validated format, never from the upload name.

Stage 3 follow-up (tech lead): the root is the project's ignored `data/` folder instead of a
cache root outside the repository (D-22), and stored inputs and outputs have no age-based
deletion (D-23). "Orphan cleanup by age" applies to temp files, work directories, and
unexpected entries only.

## Stage 4 — SQLite metadata
Goal: Persist only safe job state.

```text
Execute Stage 4 only. Add SQLite repository, migrations, and application services for batches/jobs. Persist random IDs, statuses, safe counts, hashes, software versions, timestamps, safe error codes, and randomized object references only. Do not persist source text, entity values, original filenames, page images, or detailed exceptions. Add transition concurrency tests and migration tests.
```

Acceptance: Database inspection proves no raw PII fields; transitions are atomic; corrupted/invalid transitions fail closed.

Status: complete (committed). The database is `data/metadata/jobs.sqlite3`; purge deletes
everything about a batch (D-25); reconciliation is a service call scheduled in Stage 12 (D-26).
The test suite was also trimmed to the essential tests at the tech lead's request.

## Stage 5 — Batch upload API
Goal: Receive many files safely, one request per document.

```text
Execute Stage 5 only. Implement batch creation, one-document multipart upload, batch status, deletion, and start-validation endpoints. Stream UploadFile in bounded chunks. Enforce configurable file count, per-file size, total size, PDF magic, allowed content type, random path, duplicate document handling, and request timeout behavior. Do not implement PDF content parsing or masking. Add integration tests for valid PDF, spoofed extension, oversized file, duplicate upload, malformed multipart, and cleanup.
```

Acceptance: Large upload is not read wholly into memory; one bad file does not delete or corrupt other jobs; no source filename appears in persistence/logs.

Stage 0 notes — **approved scope addition (D-15):** accept DOCX as well as PDF, identified by content (supported-pdf.md §1). Reject legacy `.doc` and macro/template files at upload. Content parsing of DOCX stays in Stage 6b.

## Stage 6 — PDF validation and extraction
Goal: Reliably classify and extract text-based PDFs.

```text
Execute Stage 6 only. Implement a PDF validator/extractor adapter using PyMuPDF. Detect malformed, password-protected, zero-page, excessive-page, and image-only PDFs. Extract page words, reading-order representation, character/span mapping, and bounding boxes. Use synthetic generated PDFs covering single-column, multi-column, Vietnamese Unicode, tables, headers, and repeated values. No detection or redaction yet.
```

Acceptance: Extraction is deterministic; unsupported/image-only documents become REVIEW_REQUIRED with safe codes; no text is persisted or logged.

Stage 0 notes: Hidden-content detection (supported-pdf.md §4) has no owner stage; proposed owner is Stage 6. PyMuPDF is AGPL-3.0/commercial (see SECURITY.md §4). The extractor must emit the format-neutral text model (D-17) that Stage 6b also emits.

## Stage 6b — DOCX validation and extraction
Goal: Safely classify DOCX CVs and extract their text into the shared text model.

```text
Execute Stage 6b only. Implement a DOCX validator/extractor adapter that reads the archive in memory with bounded limits and parses XML with a hardened parser (no DTDs, no entity resolution, no network). Enforce entry count, per-entry and total uncompressed size, compression ratio, and safe entry names. Detect encrypted, macro-enabled, template, malformed, empty, and oversized-text documents. Detect hidden content and always-strip items per supported-pdf.md §6. Extract text from body, tables, headers, footers, footnotes, endnotes, text boxes (both AlternateContent copies), content controls, and field results into the same format-neutral text model as Stage 6, with a character-to-run mapping. Use synthetic DOCX files generated at test time covering Vietnamese Unicode, runs split mid-word, tables, headers, text boxes, tracked changes, comments, and archive attacks. No detection or redaction.
```

Acceptance: Extraction is deterministic; archive and XML attacks fail closed with safe codes; hidden content becomes REVIEW_REQUIRED with category/count only; no text is persisted or logged; Stage 7 detectors can consume the output unchanged.

Stage 0 notes: Any new XML dependency (e.g. `lxml`, needed because the standard-library ElementTree rewrites namespace prefixes, which Word rejects) must be justified in the plan: license, native code, packaging impact.

## Stage 7 — Deterministic detectors
Goal: Detect email, Vietnamese phone, CCCD/CMND, salary, and reference contacts.

```text
Execute Stage 7 only. Implement a detector registry and versioned recognizers using Presidio/custom rules. Cover email, Vietnamese phone formats, CCCD/approved CMND forms with context, salary expressions, reference-section headings, and reference phone/email classification. Define normalization, confidence, overlap resolution, and false-positive controls. Use table-driven synthetic tests and property-based tests. No name inference or PDF redaction.
```

Acceptance: Annotated synthetic corpus reports per-entity precision/recall; salary findings are produced regardless of mask toggle but policy controls redaction later; raw values never enter test names/logs/snapshots.

Stage 0 notes — detectors consume only the format-neutral text model and must not import PDF or DOCX code (D-17). **Approved scope addition (D-14):** Stage 7 also covers `PASSPORT`, `DATE_OF_BIRTH` (incl. age), `GENDER`, `MARITAL_STATUS`, `NATIONALITY`, `RELIGION`, `ETHNICITY`, `HEALTH`, `PERSONAL_URL`, and labeled `POSTAL_ADDRESS`, using the cues in masking-policy.md §3. Presidio must be used without its spaCy/transformer model downloads unless separately approved; its default recognizers are English-centric.

## Stage 8 — Candidate and reference names
Goal: Add conservative, explainable contextual name detection.

```text
Execute Stage 8 only. Implement explainable candidate-name and reference-name heuristics using first-page geometry, font/layout signals, section context, explicit labels, normalization, repeated exact variants, and exclusions. Do not add external AI or remote models. Low-confidence cases must set requires_review. Build synthetic Vietnamese/English/bilingual fixtures with confounders such as company and university names.
```

Acceptance: Every name result has provenance/confidence; uncertain cases fail to review; company and education names are covered by negative tests.

Stage 0 notes — **approved scope addition (D-14):** Stage 8 also covers `FAMILY_DETAILS` sections and unlabeled `POSTAL_ADDRESS` in the header/contact block, with the same provenance, confidence, and review rules as names.

## Stage 9 — Span-to-box mapping
Goal: Convert text findings into correct page geometry.

```text
Execute Stage 9 only. Implement and test mapping from normalized text/entity spans to one or more source word boxes. Handle line breaks, split tokens, punctuation, diacritics, multiple occurrences, tables, and overlapping findings. Produce a debug representation containing synthetic text and coordinates only. Do not modify PDFs yet.
```

Acceptance: Mapping tests cover fragmented entities and duplicate occurrences; unrelated adjacent words are not included; ambiguous mappings trigger review.

Stage 0 notes: PDF-only. DOCX findings map to part + character range through the run mapping produced in Stage 6b, which Stage 10b consumes.

Stage 8 decisions (approved):
- **Overlaps.** Detection keeps partially overlapping findings of different types as separate findings. Stage 9 merges overlapping boxes into one redaction region whose label is the higher-priority type (masking-policy.md §5).
- **Unmappable findings.** A finding that maps to no source box sets `MAP_FAILED`: the document fails, and nothing is approvable. A finding with several candidate box sets redacts all of them and sets `MAP_AMBIGUOUS` (review). This replaces the interim Stage 8 behaviour, where a PDF match with no overlapping word box sets `MAP_AMBIGUOUS`.

## Stage 10 — Permanent redaction
Goal: Create secure masked PDFs.

```text
Execute Stage 10 only. Implement PdfRedactor using mapped boxes and PyMuPDF redaction annotations followed by apply_redactions. Always write a new file. Apply mandatory policy entities and conditionally salary. Use tested placeholder labels when they fit; otherwise use solid redaction. Sanitize approved metadata/attachments according to policy. Add tests proving source text cannot be extracted from redacted regions and source files remain unchanged.
```

Acceptance: Visual overlay alone is impossible in implementation; source hash is unchanged; redacted strings are absent after reopening; document remains renderable.

Stage 0 notes: Sanitization list is masking-policy.md §6, including removal of approved hidden content (always removed since D-32). Embedded images are kept unchanged (D-13); a test must prove an image outside redaction boxes survives. Per D-29, Stage 10 removes each approved hidden-content category and tests each removal; the approval itself arrives from Stage 12.

Stage 8 decision (approved): draw one redaction and one label per merged Stage 9 region, never one per overlapping finding, so labels cannot overlap.

Stage 9 decision (approved): PyMuPDF word boxes on tightly spaced lines overlap the neighbouring line vertically by about 3.5 pt. Stage 10 must include an acceptance test that redacts a word on one line and proves the words on the lines directly above and below still extract intact; if they do not, trim the overlap from the redaction rectangles, and prove the redacted word's own glyphs are still fully removed.

## Stage 10b — DOCX redaction
Goal: Create secure masked DOCX files.

```text
Execute Stage 10b only. Implement DocxRedactor that removes mapped character ranges from the XML runs and replaces them with policy labels, including every duplicate copy (AlternateContent Choice and Fallback), across all content parts. Apply mandatory policy entities and conditionally salary. Apply the DOCX always-strip list and remove approved hidden content per supported-pdf.md §6. Always write a new file named redacted-<uuid>.docx; preserve namespace prefixes and leave unrelated parts unchanged. Highlighting, shading, font color, or hidden-text formatting must never be used as redaction. Add tests proving redacted strings are absent from every decompressed part after reopening and the source file is unchanged.
```

Decision D-32 (after Stage 10): hidden content is always removed; there is no approval input.

Acceptance: No decompressed part of the output contains a redacted string (raw byte search); source hash is unchanged; output opens with an independent OOXML parser; formatting-only redaction is impossible in the implementation.

## Stage 11 — Independent verification
Goal: Prevent unverified outputs from being released.

```text
Execute Stage 11 only. Implement an independent verifier that reopens outputs, checks validity/renderability/page count, searches normalized source findings, reruns deterministic mandatory detectors, checks metadata/attachments, and returns PASSED, REVIEW_REQUIRED, or FAILED with safe reason codes. It must not trust redactor state or mock redaction in production. Add tampered-output and residual-PII tests.
```

Acceptance: Only verification PASSED may transition to COMPLETED; residual data is caught; verifier uses a fresh parser/file handle.

Stage 0 notes: Verifier also checks links and every hidden-content category. It does not inspect image content (D-13).

## Stage 11b — DOCX verification
Goal: Prevent unverified DOCX outputs from being released.

```text
Execute Stage 11b only. Extend the independent verifier to DOCX: reopen the output with a fresh handle, validate archive limits and XML well-formedness, search every decompressed part for normalized source findings, rerun deterministic mandatory detectors on freshly extracted text, and confirm that no always-strip item or hidden-content category remains and no expected part is missing. Return PASSED, REVIEW_REQUIRED, or FAILED with safe codes. It must not trust redactor state or mock redaction in production. Add tampered-output and residual-PII tests, including residue in fallback copies, document properties, comments, field codes, and thumbnails.
```

Acceptance: Only verification PASSED may transition a DOCX job to COMPLETED; residual data in any part is caught; the verifier uses a fresh parser/file handle; the limitation that rendering in Microsoft Word is not verified is documented.

## Stage 12 — Local job queue
Goal: Process large batches without freezing the laptop.

```text
Execute Stage 12 only. Add a bounded local queue with configurable worker count, one document per job, idempotent execution, safe retries, cancellation, graceful shutdown, and crash recovery from persisted states. Default to two workers and isolate CPU-heavy processing from the event loop. Ensure one malformed file cannot fail the batch. Add concurrency, duplicate-delivery, restart, cancellation, and cleanup tests.
```

Acceptance: a full 50-file batch (D-30) of lightweight synthetic jobs, plus a second batch queued behind it, runs without one process per job; API stays responsive; retries do not produce inconsistent outputs.

Decision D-29 (approved, revised by D-32/D-34): Stage 12 also owns the backend of the findings review: approve (keep → `COMPLETED`) and deny (delete → `REJECTED`, output deleted) service and API endpoints. There is no hidden-content approval, no `REVIEW_REQUIRED → QUEUED` re-run, and no reopening of FINISHED batches. Revisit whether `DETECT_FAILED` should stay retryable when defining what a retry does.

Simplifications after Stage 10 (approved; these override the prompt above where they differ):
- D-33: one background worker process, one document at a time, instead of a configurable pool. The API stays on the event loop; processing never runs there. After a restart, documents left mid-processing become `FAILED` with `JOB_INTERRUPTED` (retryable) instead of resuming. Cancel applies to queued documents only.
- D-32: remove the hidden-content review path: the Stage 6/6b extractors return the document plus alerts instead of a review, `ReviewKind.HIDDEN_CONTENT` and `hidden_content_approved` go (with a migration), the redactor is always called with removal on, and the alert kinds/counts are stored for status and the report.

Per-document time budget (security review after Stage 9): every job gets a wall-clock limit (supported-pdf.md, "Per-document processing time") that ends in `JOB_TIMEOUT`. The limit must be enforced by terminating the worker process, not by a flag the job checks, because a running regex cannot be interrupted from another thread. Detection is near-linear on the known adversarial shapes (`tests/application/test_detect_timing.py`), but the limit is the backstop for shapes not yet found. For example, text with thousands of ID-shaped hits still costs time quadratic in the hit count inside Presidio's duplicate removal: about 1.4 s at 100k characters and 5 s at 200k. Tests: a detector stub that never returns ends in `JOB_TIMEOUT`, the worker is replaced, and no partial output survives. Because detection is deterministic, decide whether a `JOB_TIMEOUT` retry is useful or should become terminal after one attempt.

## Stage 13 — HR interface
Goal: Deliver the minimal usable web UI.

```text
Execute Stage 13 only. Build a simple accessible UI with multi-file drag/drop, file list, batch-level salary toggle, upload progress, start/cancel, per-document status, safe finding counts, retry/delete, download individual masked PDF, and download masked-only ZIP/report. Poll status; do not add WebSockets. Keep display filenames in browser memory only. Never render extracted CV text. Add component and Playwright tests.
```

Acceptance: UI handles partial failures; mandatory policies cannot be disabled; ZIP contains no inputs/work files; no third-party assets/network requests.

Stage 0 notes: Accepts PDF and DOCX; downloads keep the input's format; the ZIP may contain both. Shows what hidden content was removed (kind/count/page or part) as information only (D-32), and a review-required keep/delete choice (D-34). Vietnamese and English UI strings (D-03). "Masked, not anonymized" notice. Playwright browser binaries are a dev-time download.

## Stage 14 — Runtime hardening
Goal: Protect the local service from network and browser abuse.

```text
Execute Stage 14 only. Enforce loopback binding, same-origin serving, strict Host/Origin checks, startup token/session, CSRF protection, security headers, production-disabled API docs, safe error mapping, rate/size limits, no outbound network calls, and metadata-only logging. Add tests for hostile Origin/Host, missing token, path traversal, malformed PDF, decompression/page limits, and log redaction.
```

Acceptance: A second network device cannot connect; browser requests without controls fail; security tests pass; no PII is emitted during induced errors.

Stage 0 notes: Decompression limits cover both PDF streams and DOCX archives, including a zip bomb and an XML entity payload.

## Stage 15 — Local build and launcher
Goal: Give HR a one-command macOS experience.

```text
Execute Stage 15 only. Build the React app and serve static assets from FastAPI. Create a macOS launcher that starts the server on 127.0.0.1, waits for health, opens the default browser with a safe bootstrap token, prevents duplicate instances, and shuts down cleanly. Produce installation/run/uninstall instructions. Do not yet promise signed/notarized distribution. Test on Apple Silicon and document Intel status.
```

Acceptance: HR runs one launcher; no Node development server is required; shutdown cleans temporary data according to policy; build contains no remote URLs.

Stage 0 notes: macOS only; Windows is the future stage below (D-08).

## Stage 16 — Evaluation and release candidate
Goal: Establish evidence for the presentation and decision to continue.

```text
Execute Stage 16 only. Create a synthetic/authorized evaluation harness and release checklist. Measure per-entity precision, recall, false negatives, document leakage, review-required rate, failure rate, and processing duration. Do not invent target results; compute from actual annotated fixtures. Generate a metadata-only report. Add operator guide, troubleshooting guide, architecture decision record, and demo script. Do not add new features.
```

Acceptance: All metrics are reproducible; failures are visible; release limitations are explicit; no test or report contains real candidate data.

Stage 0 notes: "Authorized" evaluation on real CVs, if ever approved, must run on the HR laptop with no Cursor/AI involvement and produce metadata-only output. The report must list photos/images as unmasked (D-13) and report metrics separately for PDF and DOCX.

## Future stage — Windows support (unscheduled)

Placeholder only (D-08). No prompt yet; the tech lead will define it. Expected
topics: Windows application root and ACL-based owner-only permissions, path
handling, launcher, and re-running the security suite on Windows.
