# Stage 2 handoff — Domain model and state machine

## Stage and objective

Stage 2 adds the pure domain model in `backend/src/cv_masking/domain/`:
- typed identifiers and value objects,
- the masking policy (mandatory entity types plus the optional salary toggle),
- format-neutral findings (PDF boxes or DOCX character ranges),
- verification results,
- the closed error-code and review-reason sets,
- the `DocumentJob` state machine and the `Batch` aggregate.

The domain has no I/O, no framework, no clock and no logging. Nothing outside the
domain uses it yet; Stage 3 onward will.

**Status: complete and committed.**

## Architecture decisions

- **Standard library only.** Modules use frozen, slotted dataclasses and `StrEnum`. An
  AST test allows only `__future__`, `collections`, `dataclasses`, `datetime`, `enum`,
  `functools`, `math`, `re`, `types`, `typing`, `uuid`, and `cv_masking.domain` itself. It
  bans `open`, `eval`, `exec`, `compile`, `__import__`, `print`, `input`, reading the clock
  (`now`, `utcnow`, `today`), and any `except` block.
- **Immutable transitions.** Each `DocumentJob`/`Batch` command checks the current state
  and returns a new object with `version + 1`. Anything not explicitly allowed raises
  `InvalidTransitionError`. Callers pass the time (`at`); it must be UTC-aware and not
  earlier than `updated_at`.
- **Fail closed on load.** `__post_init__` re-checks every structural invariant, so a
  record rebuilt from SQLite (Stage 4) with an impossible combination of fields raises
  `InvariantError`. Examples: `COMPLETED` without a `PASSED` verification, a `FAILED` job
  without a document failure code, review reasons in a non-review state, or output data
  before processing.
- **No free text anywhere.**
  - Findings hold type, location, confidence, detector id and version, replacement label,
    and a review flag; there is no text field.
  - A job keeps only `FindingCounts` (per-type counts), never individual findings.
  - Every `str` field is validated: SHA-256 hex, `word/<name>.xml` part names, lowercase
    identifiers, `MAJOR.MINOR.PATCH` versions, the policy's fixed labels, and the policy
    version.
  - Exception messages name fields, rules, commands, and states; they never include the
    offending value.
- **Identifiers are random UUID v4 wrappers** (`BatchId`, `DocumentId`, `FindingId`,
  `ObjectRef`), so an id can't encode anything about a document. `ObjectRef` is an opaque
  storage reference, never a path.
- **Policy.** `MaskingPolicy(mask_salary, version="1")`. `from_selection` raises
  `PolicyError` if any of the 16 mandatory types is missing.
  `action_for(type, confidence)` implements the masking-policy thresholds:
  - below 0.50: discard;
  - from 0.50 up to (not including) 0.85: redact and flag for review;
  - 0.85 and above: redact;
  - salary with the toggle off: detected, not redacted.

  NaN, infinity, booleans and values outside [0, 1] are rejected.
- **Review kinds.** Every `ReviewReason` has a kind:
  - blocking: delete only;
  - hidden_content: approve, then continue processing;
  - findings: approve the already-verified output;
  - verifier: deny only.

  `approve_review` succeeds only when all reasons are hidden_content (goes to `QUEUED`)
  or all are findings with a `PASSED` verification (goes to `COMPLETED`).
- **Stage and format restrictions on codes.**
  - `reject_upload` and `fail` accept only codes that belong to the current stage (listed
    in `docs/error-codes.md` §3).
  - PDF-only codes are refused for a DOCX job and vice versa.
  - `SECURITY_*` codes can never become a document's code.
- **Retries.** `requeue_after_interruption` (from `PROCESSING` or `VERIFYING`) discards
  the output, policy and reasons, and keeps the attempt count. On the third attempt the
  job goes to `FAILED` with `JOB_INTERRUPTED`.
- **Batch.**
  - The salary toggle is editable only while `OPEN`.
  - `start` needs at least one document.
  - Adding a document fails once the batch holds 100.
  - `finish` needs the state of every document, and each must be terminal or
    `REVIEW_REQUIRED`.
  - `purge` works from any state, once.

### Deviations from the approved plan

1. **Exception names.** The plan said `InvariantViolation` etc. Ruff's N818 rule requires
   an `Error` suffix, so they're `DomainError`, `InvariantError`, `PolicyError` and
   `InvalidTransitionError`.
2. **New error code `JOB_EXPIRED` (T).** The approved retention rule (inputs deleted 24 h
   after upload) needs a code for a job still in review at that point. `expire` moves
   `REVIEW_REQUIRED` to `FAILED` with this code.
3. **Two approval flags on `DocumentJob`.** `hidden_content_approved` is kept through
   processing, so Stage 10's sanitizer knows HR approved removal. `findings_review_approved`
   records that a `COMPLETED` job went through HR review.
4. **Two extra invariants found during self-review.**
   - A `FAILED` job may not carry a `SECURITY_*` code or a code for the other format.
   - A post-processing review may not hold a `FAILED` verification.

## Files added/changed

| File | Change |
|---|---|
| `backend/src/cv_masking/domain/__init__.py`, `errors.py`, `_validation.py`, `ids.py`, `formats.py`, `limits.py` | Added |
| `backend/src/cv_masking/domain/codes.py`, `policy.py`, `findings.py`, `verification.py` | Added |
| `backend/src/cv_masking/domain/document_job.py`, `batch.py` | Added |
| `backend/tests/domain/domain_builders.py` | Added (synthetic builders, no document content) |
| `backend/tests/domain/test_{document_transitions,document_guards,document_invariants,document_properties}.py` | Added |
| `backend/tests/domain/test_{batch,policy,value_objects,codes,no_pii_fields}.py` | Added |
| `backend/tests/architecture/test_domain_boundaries.py` | Added |
| `backend/pyproject.toml`, `backend/uv.lock` | `hypothesis` added to the dev group |
| `docs/error-codes.md` | State diagram finalized. Review-reason table added. Blocking codes marked `—`. `JOB_EXPIRED` added. Stage and format rules documented. |
| `docs/stage-plan.md`, `README.md` | Status updated |
| `docs/stage-handoffs/stage-2.md` | Added (this file) |

## Dependencies (security and packaging impact)

| Package | Version | Scope | Notes |
|---|---|---|---|
| hypothesis | 6.168.1 | dev only | Property-based testing. MPL-2.0, pure Python, no network use. Not in the runtime package. |
| sortedcontainers | 2.4.0 | dev only (via hypothesis) | Apache-2.0, pure Python. |

The tests set `database=None` and `derandomize=True`, so runs are deterministic and write
no example database. Hypothesis still creates a `backend/.hypothesis/` cache directory.
It's covered by `.gitignore` and only ever holds synthetic values. No runtime dependency
was added.

## Commands run and exact results

1. `uv add --dev hypothesis`: resolved `hypothesis 6.168.1` and `sortedcontainers 2.4.0`.
2. First `ruff check src`, run before any tests existed:
   - N818 on all four exception names; fixed by renaming them.
   - S105 false positive on the code name `SECURITY_TOKEN_INVALID`; suppressed with a
     reasoned `noqa`.
   - Two SIM102 nested `if` blocks in `document_job.py`; merged.
3. First full `pytest`: 1 failure. `test_domain_objects_are_immutable` hit a CPython quirk:
   assigning an unknown attribute on a frozen, slotted dataclass raises `TypeError` rather
   than `FrozenInstanceError`. The assignment is still refused, and the test now accepts
   either exception.
4. First strict `mypy` over the tests found 3 typing issues in the tests (an unused ignore,
   a deliberate cross-type comparison, an untyped lambda tuple); fixed.
5. **Mutation check.** I planted four bugs in `document_job.py`, one at a time, and ran
   `pytest tests/domain`. Each was caught (exit 1), and the file was restored and verified
   with `cmp`:
   - Allowing `cancel` from `REVIEW_REQUIRED`: caught by
     `test_cancellable_states_are_exactly_the_non_terminal_non_review_states`.
   - Allowing a blocking review to be approved: caught by
     `test_blocking_review_cannot_be_approved[pdf]`.
   - Removing the `COMPLETED`-needs-`PASSED` invariant: caught by
     `test_impossible_stored_job_is_rejected[completed-without-verification]`.
   - Expiring before 24 h: caught by `test_expire_requires_the_full_retention_window`.
6. **Final** `make check`: exit 0.
   - `ruff format --check`: `33 files already formatted`
   - `ruff check`: `All checks passed!`
   - `prettier --check`: `All matched files use Prettier code style!`
   - `eslint . --max-warnings=0`: clean
   - `mypy` (strict, `src` and `tests`): `Success: no issues found in 33 source files`
   - `tsc --noEmit`: clean
   - `pytest`: `666 passed in 1.89s`; 0 skipped, 0 warnings (warnings are errors)
   - `vitest run`: `Test Files 3 passed (3)`, `Tests 7 passed (7)`

## Tests added

629 new backend tests (666 in total).

| Test file | Count | What it proves |
|---|---|---|
| `test_document_transitions.py` | 161 | Every one of the 14 commands against every one of the 11 states. Only the documented transitions succeed; each success bumps `version` by one and keeps the ids and `created_at`. Terminal states reject every command. The matrix covers every public command method. |
| `test_document_guards.py` | 93 | `reject_upload` and `fail` accept exactly the codes listed per stage and format (checked against a hand-written list, not derived from the implementation). Validation review accepts only blocking and hidden-content reasons of the right format. Hidden-content approval sets the flag and requeues. Blocking, mixed and verifier reviews can't be approved. A findings approval needs a `PASSED` verification. Deny works on every review kind. Expiry happens at exactly 24 h and not 1 µs earlier. Attempt limit, requeue discarding output, verification ref and format checks, the most serious failure code winning. Time can't go backwards and must be UTC. |
| `test_document_invariants.py` | 63 | 51 impossible stored-job combinations are rejected, covering types, time, upload, processing, review and outcome fields. Every valid state round-trips. |
| `test_document_properties.py` | 1 (600 examples) | Random command sequences with random arguments, starting from any state (including every review variant), never raise anything but `InvalidTransitionError`. Terminal states are absorbing, `version` rises by exactly one per transition, attempts stay at or below 3, `COMPLETED` always has a `PASSED` verification of its own output, and error codes appear only on `FAILED`/`CANCELLED` and never as `SECURITY_*`. |
| `test_batch.py` | 29 | Salary toggle and its policy. Exactly 100 files. The batch is locked after start. `finish` rules. `purge` works once. Impossible stored batches are rejected. |
| `test_policy.py` | 45 | The 16 mandatory types plus salary. Removing any single mandatory type raises `PolicyError`. Threshold boundaries use `nextafter` just below 0.50 and 0.85. Unmasked salary is reported, not redacted. NaN, infinity, bool, out-of-range, string and `None` confidences are rejected. A property test checks that mandatory types above the discard threshold are always redacted. |
| `test_value_objects.py` | 101 | Ids reject UUID v1, v5, nil, strings and `None`. Digest format. Bounding boxes reject degenerate, NaN, infinite and bool coordinates. Page bounds 1–30 and the box limit. DOCX part names reject traversal, absolute paths, `_rels`, `customXml`, `docProps`, media, uppercase and newlines. Finding fields reject free text (a name, an email) in the detector id and label. `FindingCounts` ordering and uniqueness. Verification-result rules. |
| `test_codes.py` | 57 | Parses `docs/error-codes.md`: the R/T codes equal `ErrorCode`, the R codes equal `RETRYABLE_ERROR_CODES`, the `—` rows equal `ReviewReason`, and the review-kind table equals `REVIEW_REASON_KINDS`. No duplicates. Groups and formats. The code group mapping is read-only. |
| `test_no_pii_fields.py` | 41 | The exact field list of every domain dataclass. No field name contains `text`, `raw`, `content`, `name`, `file`, `path`, `snippet`, `email`, `phone`, `address` and similar, apart from three reviewed exceptions. The set of `str` fields is exactly the validated set. Objects are slotted and immutable. Nine invalid-input attempts using a synthetic marker (Vietnamese name, phone, email) never echo it in the exception. |
| `architecture/test_domain_boundaries.py` | 38 | Per domain file: standard-library imports only, no I/O, dynamic code or clock reads, no `except`. Includes a self-test showing the checker catches `os`, `pathlib` and `cv_masking.api`. |

## Security/privacy review

- **No document data.** No code reads, stores or logs document content. Findings can't hold
  text. Every string field is pattern-checked, so free text such as a name or email is
  rejected (tested).
- **Errors.** Exception messages contain only field, rule, command and state names (tested
  with a synthetic Vietnamese name, phone and email marker).
- **Fail-closed paths.**
  - `COMPLETED` requires a `PASSED` verification of the job's own output, both as a
    transition guard and as a load-time invariant.
  - A verifier `REVIEW_REQUIRED` result can't be approved.
  - Blocking reasons can't be approved.
  - Unknown or out-of-stage codes are refused.
- **Retention hooks.** `expire` and `JOB_EXPIRED` model the 24 h input deletion. Stage 3
  performs the deletion.
- **No network, no I/O, no subprocess.** Enforced by the AST boundary test. Tests still run
  with sockets blocked.
- **Test data.** All fixtures are synthetic: `synthetic-verifier`, `synthetic@example.test`,
  the placeholder `Nguyen Van A`, `0900000000`. No real CV was used or opened.
- **Diff review.** No remote URLs, no new runtime dependencies, no broad `except`, no
  `TODO`s, no skipped tests. The single `type: ignore` in production code is on the
  generic `dataclasses.replace(**changes)` call, whose result is re-validated by
  `__post_init__`.

## Known limitations

- **Not wired in yet.** Nothing outside the domain uses it; repositories (Stage 4), the API
  (Stage 5) and the worker (Stage 12) will.
- **Batch purge.** `purge` is a domain transition only. Deleting the files is Stage 3.
- **Batch `finish` trusts its caller.** It takes a list of document states rather than
  loading documents; the application service in Stage 4/5 must pass the batch's real
  documents.
- **Document count is limited, total size isn't.** `Batch` limits the number of documents,
  not the batch's total bytes (`UPLOAD_BATCH_SIZE_LIMIT`). That limit needs the configured
  value and belongs to the upload service (Stage 5).
- **Detector ids may contain dots and hyphens** (e.g. `regex.email`). The pattern is
  lowercase ASCII only, so it can't hold Vietnamese text, spaces or `@`.
- **Findings reasons after a requeue.** When a job is requeued, `output_written` computes
  its findings reasons again; reasons from the interrupted attempt are discarded.

## Manual verification steps

1. Run `make check`. It should end with `666 passed` and `Tests 7 passed (7)`.
2. Run `cd backend && uv run --locked pytest tests/domain/test_document_transitions.py -q`
   and read the ids (e.g. `review_required-approve_review`). Each state/command pair is
   listed.
3. Try the rehydration guard from `backend/`:

   ```sh
   uv run --locked python -c "
   import sys; sys.path.insert(0, 'tests/domain')
   from domain_builders import completed, rebuild
   rebuild(completed(), verification=None)"
   ```

   It should fail with
   `InvariantError: a COMPLETED DocumentJob needs a PASSED verification`.
4. Compare the §2 diagram and review-reason table in `docs/error-codes.md` against
   `document_job.py`. `test_codes.py` fails if the code tables drift.

## Questions/decisions for the tech lead

All three were answered after the Stage 2 commit and are implemented in the follow-up
below.

1. **`JOB_EXPIRED`.** Accepted (D-19).
2. **Order of verification failure codes.** A fixed precedence was chosen (D-20).
3. **Pre-commit guard and npm install-script policy.** The tech lead asked for the
   agent's recommendation, to be implemented if important. Both were built (D-21).

## Follow-up after tech-lead answers

### Changes

- **Verification precedence.** `VERIFY_FAILURE_PRECEDENCE` in `domain/verification.py`
  ranks the codes:
  1. `VERIFY_RESIDUAL_FINDING`
  2. `VERIFY_RESIDUAL_DETECTION`
  3. `VERIFY_RESIDUAL_METADATA`
  4. `VERIFY_OUTPUT_INVALID`
  5. `VERIFY_PAGE_COUNT_MISMATCH`
  6. `VERIFY_STRUCTURE_MISMATCH`

  `VerificationResult.primary_failure_code` picks the highest-ranked code, and
  `record_verification` stores it as the job's `error_code`, replacing the alphabetical
  minimum. All codes stay on the verification result. The order is documented in
  `docs/error-codes.md` and checked by a doc-sync test.
- **File guard.** `scripts/check-repo-files.sh` (bash 3.2, the macOS system shell) checks
  the content in the git index.
  - `--staged` runs from the pre-commit hook `scripts/git-hooks/pre-commit`.
  - `--all` is the new `make guard` target, and runs first in `make check`.
  - `make install` now runs `make hooks`, which is `git config core.hooksPath
    scripts/git-hooks`. It changes only this repository's local git config.
  - It refuses blocked extensions (case-insensitive), content signatures (PDF, ZIP/DOCX,
    OLE/DOC, RTF, SQLite, PNG, JPEG, GIF, gzip, 7z, RAR) under any name, and files over
    1 MiB. The one exception is `tests/fixtures/synthetic/**/synthetic-*`, which still
    has the size limit.
  - Output is counts only, never paths, so an agent-run commit can't put a CV's file name
    into chat.
- **npm.** `ignore-scripts=true` added to `frontend/.npmrc`. No dependency needs an
  install script. `fsevents` ships a prebuilt binary, and npm had already skipped its
  unapproved scripts.

### Files

| File | Change |
|---|---|
| `backend/src/cv_masking/domain/verification.py`, `document_job.py` | Precedence and `primary_failure_code` |
| `backend/tests/domain/test_value_objects.py`, `test_document_guards.py`, `test_codes.py` | Precedence tests |
| `scripts/check-repo-files.sh`, `scripts/git-hooks/pre-commit` | Added (executable) |
| `backend/tests/repo/test_file_guard.py`, `test_npm_policy.py` | Added |
| `Makefile` | `hooks` and `guard` targets; `install` depends on `hooks`; `check` runs `guard` first |
| `frontend/.npmrc` | `ignore-scripts=true` |
| `SECURITY.md`, `README.md`, `docs/error-codes.md`, `docs/product-scope.md` (D-19 to D-21) | Updated |

### Subprocesses (security and packaging impact)

The guard tests run `git` and the guard script with `subprocess.run`:
- fixed argument lists, no shell;
- inside a pytest temporary directory;
- with `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, and a temporary `HOME`, so
  your git configuration and credentials are never used;
- with only synthetic bytes;
- with no network (sockets stay blocked for the Python process, and git only touches the
  local repository).

The subprocesses are dev-only; nothing ships in the runtime package. There are no new
dependencies.

### Commands and results

- `npm ci --offline`: `added 236 packages … found 0 vulnerabilities`, with no
  install-script warning.
- Mutation check of the guard. Each planted bug was caught, then the file was restored and
  verified with `cmp`:
  - content check disabled: 11 tests failed;
  - fixture exception widened to any `*/synthetic/*` path: 3 failed;
  - size limit disabled: 3 failed.
- First run of the npm policy test failed because it flagged `preview` as a `pre` hook.
  The test now checks only real `pre<script>`/`post<script>` pairs.
- **Final** `make check`: exit 0.
  - Guard: `71 file(s) checked, none refused`
  - Ruff: `36 files already formatted`, `All checks passed!`
  - Prettier and ESLint: clean
  - mypy: `Success: no issues found in 35 source files`
  - `tsc`: clean
  - pytest: `718 passed`
  - vitest: `Tests 7 passed (7)`

### Tests added

| Test file | Count | What it proves |
|---|---|---|
| `test_value_objects.py`, `test_document_guards.py`, `test_codes.py` | +9 | The precedence ranks every `VERIFY_*` code exactly once, with leaks first. The primary code is the highest ranked for each subset. There's no primary code on non-failed results. The job stores `VERIFY_RESIDUAL_METADATA` over `VERIFY_OUTPUT_INVALID`, where the alphabetical order would differ. The doc order matches the code. |
| `repo/test_file_guard.py` | 41 | Source files pass. 14 blocked extensions are refused, including uppercase. 8 content signatures are refused under a `.txt` name. A file with no extension is checked by content. The 1 MiB limit is exact. Synthetic fixtures pass, and 5 near-miss paths don't. Fixtures still have the size limit. Index content is checked, not the working tree. `--staged` vs `--all`. Output never contains the file name. Tabs, newlines and Vietnamese characters in names are handled. A bad mode exits 2. An end-to-end hook blocks the commit and then allows it once the file is unstaged. |
| `repo/test_npm_policy.py` | 2 | `.npmrc` refuses install scripts, and `package.json` has no lifecycle or hook scripts. |

### Known limitations

- The hook can be skipped with `git commit --no-verify`; `make check` still catches the
  file.
- Plain-text personal data typed into a source or Markdown file isn't detected. Only file
  types and signatures are.
- A future synthetic fixture over 1 MiB would need a deliberate change to the guard.
- `make guard` takes a few seconds because it reads each blob from the index.

### Suggested commit message

```
chore: verification precedence, repo file guard, npm install-script policy

Rank VERIFY_* failure codes (residual finding first) and store the most
serious one on the job. Add scripts/check-repo-files.sh as a pre-commit
hook and make check step that refuses document, image, archive, database,
and log files by extension and content signature, and files over 1 MiB,
except tests/fixtures/synthetic/**/synthetic-*; it never prints paths.
Disable npm install scripts. Record decisions D-19 to D-21.
```

## Suggested commit message

```
feat(domain): stage 2 domain model and document state machine

Add a pure-stdlib domain package: UUIDv4 ids, closed ErrorCode/ReviewReason
sets with review kinds, masking policy (16 mandatory types plus salary
toggle, 0.50/0.85 thresholds), format-neutral findings (PDF boxes, DOCX
ranges) without text fields, verification results, and immutable
DocumentJob/Batch aggregates whose invariants fail closed on rehydration.
COMPLETED requires a PASSED verification; verifier reviews are deny-only.
Add JOB_EXPIRED and finalize docs/error-codes.md. Tests: full transition
matrix, guards, rehydration invariants, hypothesis properties, doc sync,
no-PII field allowlists, and an AST domain-boundary check (666 passing).
```
