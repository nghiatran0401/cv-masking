# Stage 12 handoff — Local job queue

## Stage and objective

Stage 12 connects the Stage 6–11b pieces into a background job queue. When HR
starts a batch, each document is validated, redacted, and independently
verified in its own format. Nothing blocks the API.

The stage prompt was narrowed by the approved simplifications recorded in the
stage plan:

- **D-33:** one worker process handling one document at a time; no restart
  resume; cancel applies only to waiting documents.
- **D-32:** hidden content is always removed; there is no approval step.
- **D-29/D-34:** the backend for findings review, where HR keeps (approve) or
  deletes (deny) a held document.

Stage 12 also owns the per-document time budget, the sweeper and reconcile
schedule, and recovery and shutdown (data-retention §5.4 and §5.8).

## Architecture decisions

- **The queue is the persisted state** (`application/worker.py`,
  `WorkerService`).
  - The next job is the oldest `UPLOADED` document of the oldest `RUNNING`
    batch, ordered by `created_at` and then id.
  - There is no in-memory backlog, so the queue is bounded by the batch
    limits, and nothing is lost on restart.
  - A document is claimed by the optimistic change `UPLOADED → VALIDATING`
    inside a `BEGIN IMMEDIATE` transaction. A second delivery, from the same
    or another thread, finds the document already taken and returns `None`.
    This is how duplicate delivery stays idempotent.
- **One isolated worker process** (`adapters/worker/process.py`,
  `SubprocessProcessor`).
  - It is started with `multiprocessing` `spawn`: the same Python interpreter,
    an anonymous duplex pipe, no shell, no socket, and no other program. It is
    started lazily, reused for every document, and replaced only after a
    timeout or crash.
  - One document is a session of three calls: validate, then process, then
    verify. Then `forget`.
  - The worker only reads stored files. It returns the redacted output as
    bytes. The API process stores the output, re-checks the input hash, and
    writes every metadata change.
- **Worker replies are never unpickled** (`adapters/worker/codec.py`).
  - Each reply is a JSON header plus an optional raw output frame, read with
    bounded `recv_bytes` (64 KiB header, 20 MB output).
  - Replies are rebuilt through the domain constructors
    (`ValidationReport`, `ProcessingReport`, `VerificationReport`,
    `VerificationResult`), which re-check every invariant: stage-appropriate
    codes, review kinds, and bounded non-empty output.
  - Pickle is used only in the trusted direction: spawn passes the pipe end
    and the module-level factory to the child.
- **Time budget.**
  - The budget starts when the worker is ready, because the first start
    imports Presidio and PyMuPDF in about 1.5 s. It covers validate, process
    and verify together.
  - If the budget expires, the process is terminated (then killed after 2 s)
    and the document fails with `JOB_TIMEOUT`.
  - A regex or a parser that hangs cannot be interrupted from a thread; ending
    the process can.
- **Outcome mapping** (`WorkerService._drive`):

  | What happened | Result |
  |---|---|
  | Timeout | `JOB_TIMEOUT` |
  | Worker died or sent an unreadable reply | `INTERNAL_ERROR` |
  | Shutdown while the worker holds the document | `interrupt` → `JOB_INTERRUPTED` |
  | Unexpected exception in the API process | `INTERNAL_ERROR` |
  | Output could not be stored | `REDACT_OUTPUT_WRITE_FAILED` |
  | Input changed while its output was being stored | `STORAGE_INTEGRITY_FAILED`, output deleted |

  Every failure settles only its own document. A document cancelled or purged
  meanwhile is left alone; its stored output, if any, is discarded.
- **Pipeline** (`application/processing.py`, `DocumentPipeline`).
  - It runs inside the worker and holds the extracted text and findings
    between the three calls.
  - It forgets them after verification, at the start of the next document,
    and on any error.
  - `RedactionService` now returns output bytes and no longer stores them.
    `ValidationService` was removed; `DocumentPipeline.validate` replaces it.
- **Loop** (`WorkerLoop`).
  - One daemon thread named `cv-masking-worker`.
  - `start()` runs `recover()` (held documents → `JOB_INTERRUPTED`), then the
    sweeper and reconcile, all before the first request.
  - It runs maintenance again every 10 minutes and polls every second.
    `notify()` from `POST /start` wakes it immediately.
  - `stop()` gives the document in progress 10 s, then closes the processor.
    The document becomes `JOB_INTERRUPTED`, and the call returns once the
    process is dead.
  - FastAPI's lifespan calls `start` and `stop` through `asyncio.to_thread`,
    so the event loop never blocks.
- **D-32 in code.**
  - The extractors return the document with `hidden` alerts instead of a
    review.
  - `ReviewKind.HIDDEN_CONTENT`, `PDF_HIDDEN_CONTENT`, `DOCX_HIDDEN_CONTENT`,
    `hidden_content_approved`, and the redactors' `remove_hidden` flag are
    gone.
  - `DocumentJob.hidden_removed: HiddenContentCounts` records the kinds and
    counts removed.
  - The DOCX redactor now fails closed with `REDACT_SANITIZE_FAILED` if any
    hidden content is left in its own output.
- **Domain changes.**
  - `CANCELLABLE_STATES = {CREATED, UPLOADED, QUEUED}`.
  - `interrupt()` from `VALIDATING`, `PROCESSING` or `VERIFYING` goes to
    `FAILED` with `JOB_INTERRUPTED`. It replaces `requeue_after_interruption`.
  - `can_approve_review` is true only when every reason is a findings reason
    and verification passed.
  - `DETECT_FAILED` and `JOB_TIMEOUT` are no longer retryable (D-41).
- **Migration 2.**
  - Documents that a Stage 11 database held for hidden-content approval fail
    with `JOB_INTERRUPTED`, and those reasons are deleted.
  - The `hidden_content_approved` column is dropped.
  - A new STRICT, WITHOUT ROWID table `document_hidden_content` holds
    `(document_id, category, count)`: the category is constrained to
    `[a-z_]` (1–32 characters) and count ≥ 1.
- **API.**
  - New endpoints, each with `{expected_version}`:
    - `POST /api/batches/{b}/documents/{d}/cancel`
    - `POST /api/batches/{b}/documents/{d}/approve`
    - `POST /api/batches/{b}/documents/{d}/deny`
  - An illegal transition or a stale version returns 409. A document from
    another batch returns 404.
  - `DocumentView` gains `review_reasons`, `can_approve`, `finding_counts`
    and `hidden_removed`. These are codes and counts only.
- **Config.** `CV_MASKING_JOB_TIMEOUT_SECONDS`: default 120, range 1–600.
- **SQLite side-file race (found by the new API-responsiveness test).** When
  the API thread and the worker thread use the store at once, a closing
  connection can unlink `-wal`/`-shm` between our `open` and `fstat`. The
  file check then saw `st_nlink == 0` and refused with
  `STORAGE_PATH_REJECTED`. A side file that is already unlinked is now
  skipped; SQLite reopens side files by name and never reuses an unlinked
  one. A main database with zero links is still refused. A regression test
  reproduces the race deterministically.

## Subprocess: security and packaging impact (SECURITY.md §4)

- **What it runs:** `multiprocessing` with the `spawn` context starts
  `sys.executable` (the app's own interpreter) with multiprocessing's
  bootstrap. On macOS spawn also starts multiprocessing's small
  `resource_tracker` helper, which runs the same interpreter.
- **What it doesn't do:** no shell, no external program, no network. The
  architecture test allows `multiprocessing` only in
  `adapters/worker/process.py` and forbids `subprocess`, `os.system`, `popen`,
  `fork`, `exec*`, and `spawn*` everywhere. The worker pipe uses only
  `send_bytes`/`recv_bytes`, never `send`/`recv` (pickle).
- **No new dependencies;** `pyproject.toml` and `uv.lock` are unchanged.
- **Packaging (Stage 15):** the bundled interpreter must support spawn (it
  must be able to re-import `cv_masking` by module name). A frozen
  single-binary build would need `multiprocessing.freeze_support()`; the
  planned D-39 `.command` launcher with a bundled Python environment does not.
- **Processes:** at most one worker plus the resource tracker; never one per
  document.

## Files added/changed

- **Added:**
  - `backend/src/cv_masking/ports/processing.py`
  - `backend/src/cv_masking/application/processing.py`
  - `backend/src/cv_masking/application/worker.py`
  - `backend/src/cv_masking/adapters/worker/{__init__,codec,process}.py`
- **Removed:** `backend/src/cv_masking/application/validation.py`.
- **Changed:**
  - domain: `codes`, `document_job`, `hidden`, `limits`;
  - ports: `extraction`, `redaction`;
  - adapters: the PDF and DOCX extractors and redactors; SQLite `migrations`,
    `rows` and `store`;
  - application: `redaction`, `__init__`;
  - `config`;
  - API: `app`, `batches`, `runtime`.
- **Tests added:**
  - `tests/application/test_worker.py`
  - `tests/application/test_worker_process.py`
  - `tests/application/test_worker_codec.py`
  - `tests/application/worker_stubs.py` (stub pipelines imported inside the
    worker)
  - `tests/api/test_document_actions.py`
- **Tests updated:** domain builders, transitions, guards, properties, codes,
  no-PII fields, value objects; schema and migrations; database files;
  extraction, redaction and verification tests for D-32; job service; config;
  architecture.
- **Docs:**
  - `docs/error-codes.md`: state diagram and review table without hidden
    content; `interrupt`; cancel states; `DETECT_FAILED` and `JOB_TIMEOUT`
    marked `T`; `JOB_INTERRUPTED` meaning; no automatic retries.
  - `docs/supported-pdf.md`: 120 s budget.
  - `docs/data-retention.md`: §5.1, §5.3, §5.4, §5.5, §5.8.
  - `docs/product-scope.md`: scope line and D-41.
  - `THREAT_MODEL.md`: TB-2 → TB-3, TB-3 → TB-4, T-19, T-24, T-25.
  - `docs/stage-plan.md`, `README.md`, and this handoff.

## Commands run and exact results

- `make check` (after the final code change):
  - file guard: 183 files checked, none refused;
  - `ruff format --check`: 145 files already formatted;
  - `ruff check`: all checks passed;
  - `mypy --strict`: no issues in 143 source files;
  - pytest: **684 passed** in 77 s;
  - vitest: 3 files, 7 tests passed.
- Worker, metadata and API tests repeated three times in random order: 97
  passed each time (about 39 s per run).
- The side-file regression test fails without the store fix (1 failed,
  3 passed) and passes with it (4 passed).

## Tests added

- **Worker service, in-process** (35 tests):
  - every outcome: completed; malformed → `FAILED`; blocking and findings
    reviews; hidden content counts;
  - keep and delete of findings reviews; a verifier/blocking review is
    deny-only;
  - one malformed file does not fail the batch;
  - an unexpected error fails only its document;
  - timeout, crash and shutdown at each of validate, process and verify → the
    right code and no output;
  - a worker that cannot start claims nothing;
  - output store full; input tampered with during processing;
  - maintenance survives storage errors;
  - queue order across batches; an OPEN batch is never served;
  - duplicate delivery, sequential and from two concurrent threads, processes
    the document once;
  - repeated runs of the same file give identical outputs;
  - a cancelled document is never processed; cancel is refused while the
    worker holds a document;
  - a purge during each step leaves no files;
  - recovery;
  - the loop: recovers, cleans, processes notified batches, runs maintenance
    on its interval, and survives a worker that cannot start.
- **Real worker process** (13 tests):
  - 50-file batch (49 light plus 1 malformed) and a 10-file batch behind it:
    all settle, `started == 1`, both batches FINISHED, no inputs or work
    files left;
  - the production pipeline with a detector that never returns →
    `JOB_TIMEOUT`, process dead, no outputs or work files, replaced for the
    next document;
  - a stub that hangs times out and the next document completes;
  - an `os._exit` crash → `INTERNAL_ERROR` and the next document completes;
  - a failing factory claims nothing;
  - graceful shutdown with a hung document → `JOB_INTERRUPTED`, process
    dead, the waiting document stays `UPLOADED`;
  - restart recovery;
  - API stays responsive: `/api/health` latency stays under 0.5 s while the
    worker burns CPU;
  - production pipeline end to end on synthetic PDF and DOCX, with and
    without hidden content: verification PASSED and the hidden categories
    recorded.
- **Codec:** round trips for every message; malformed JSON, codes, reasons,
  counts, categories, times, refs and ids are refused.
- **Domain:** `HiddenContentCounts` totals and validation.
- **Migrations:** v1 → v2 upgrade (a hidden-held document →
  `JOB_INTERRUPTED`, a blocked one untouched); schema allowlist including
  `document_hidden_content`.
- **API:** approve, deny and cancel, including 409 on illegal transitions and
  stale versions and 404 for the wrong batch; the view's field allowlist.
- **Architecture:** process isolation, JSON-only pipe, and D-32 extractor and
  redactor tests.

## Security/privacy review

- **No PII crosses the pipe except the redacted output bytes.** Requests
  carry refs, hashes, format, size and policy; replies carry codes, counts,
  categories, verifier id and version, and times.
- **Logs** contain document ids, codes, counts, states and exception type
  names only.
- **No new text columns:** the new table holds a constrained category and a
  count. The schema allowlist test and the free-text refusal test cover it.
- **Transient text:** extracted text lives only in the worker's memory and is
  dropped after verification or with the process.
- **Loopback bind unchanged; no network code.**
- **COMPLETED still requires a PASSED verification.** Approve requires
  findings-only reasons and PASSED.
- **Test fixtures are synthetic:** marker bytes and the existing synthetic
  CV builders. Test ids and messages carry type names and indexes only.
- **Scope:** no UI (Stage 13) and no rate limit or token work (Stage 14).

## Known limitations

- **No automatic retries (D-33).** HR retries by re-uploading.
  `JOB_INTERRUPTED` is the only worker code marked retryable.
- **The first document pays the worker start time** (about 1.5 s); the
  budget excludes it. A worker that fails to start leaves documents waiting
  and the loop retries every second.
- **PDF visible text can be dropped.** A visible word that overlaps an
  invisible-text box is dropped from extraction (Stage 6 behaviour). Before
  D-32 such documents stopped for review; now they are processed. The
  verifier still reruns the rules on the output.
- **PDF form and annotation text is detected and redacted in place** before
  the annotation is removed. Over-redaction of text drawn underneath is
  possible (a `MAP_AMBIGUOUS` review).
- **Queue order within a batch** is `created_at` and then document id; two
  uploads in the same microsecond are ordered by id.
- **Shutdown grace (10 s) is fixed.** A killed API process (SIGKILL) takes
  the daemon worker with it; the next start recovers the document.

## Manual verification steps

1. `make check`
2. `cd backend && uv run --locked python scripts/run_pytest.py -q tests/application/test_worker_process.py -k "full_batch or never_returns or responsive"`
3. Optional, with synthetic files only: `make dev`, create a batch, upload a
   synthetic CV from the test builders, start it, and poll
   `GET /api/batches/<id>`. The document reaches `completed` or
   `review_required` with `hidden_removed` and `finding_counts`.

## Questions/decisions for the tech lead

1. **D-41, terminal codes.** Should `DETECT_FAILED` and `JOB_TIMEOUT` stay
   terminal (`T`)? Detection is deterministic, so a re-upload fails the same
   way.
2. **D-41, time budget.** Is 120 s per document right, covering validation,
   processing and verification together (configurable up to 600 s)?
3. **D-41, cancel.** Should cancel include `CREATED` (upload in progress) as
   well as `UPLOADED` and `QUEUED`?
4. **D-41, shutdown.** Is 10 s shutdown grace, then `JOB_INTERRUPTED`,
   acceptable?
5. **D-41, migration.** Is failing documents held for hidden-content
   approval with `JOB_INTERRUPTED` acceptable, rather than re-queuing them?
6. **Packaging.** Confirm the Stage 15 launcher keeps a normal Python
   environment (no frozen binary), so spawn needs no extra handling.

## Suggested commit message

`feat(queue): single isolated worker process with persisted queue, time budget, recovery, cancel, and findings review endpoints (Stage 12)`
