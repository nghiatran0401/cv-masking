# Stage 4 handoff — SQLite metadata

## Stage and objective

Stage 4 persists batch and document state in a local SQLite database and adds the
application services that change it. The database can hold only safe values: random IDs,
states, versions, timestamps, sizes, SHA-256 hashes, per-type finding counts, closed error
and review codes, and software versions. There is still no API endpoint and no document
processing; nothing in the running app calls these services yet.

At the tech lead's request, the whole backend test suite was also trimmed to the tests
that guard security, privacy, data integrity, and the state machine (919 → 150 tests).

## Architecture decisions

- **Ports.**
  - `ports/metadata.py` defines `MetadataReader`, `MetadataTransaction`, `MetadataStore`,
    `ObjectUse`, `RecordNotFoundError`, and `ConcurrentUpdateError`.
  - `ports/clock.py` defines `Clock`.
  - `ObjectStore` gained `list_objects()`, which returns `ObjectListing(ref, format,
    modified_at)`.
- **Adapter `adapters/sqlite`** (stdlib `sqlite3` only; no new dependency):
  - **Location.** The database is `data/metadata/jobs.sqlite3` (D-25). `StorageRoot.prepare`
    creates `metadata/` with mode `0700`. The sweeper never looks inside it.
  - **Files are checked on every connection.** The database is created with mode `0600`
    using `O_EXCL | O_NOFOLLOW`. The database and its `-wal`/`-shm` files must be regular,
    owned by the user, singly linked, and not readable by others. A missing database is
    never silently recreated.
  - **Hardened connection settings.**
    - WAL mode, `synchronous=FULL`, `foreign_keys`, `secure_delete`, `cell_size_check`.
    - `trusted_schema=OFF`, defensive mode, and no double-quoted string literals.
    - `quick_check` runs on open.
  - **Schema.** Every table is `STRICT` and has only INTEGER and TEXT columns. Every text
    column has a CHECK that allows only a UUID, a hex hash, a lowercase or uppercase code,
    or a version string, so free text is refused at the database level.
  - **Migrations.**
    - Each migration is recorded with its SHA-256 checksum in `schema_migrations`, and
      `user_version` tracks the schema version.
    - After migrating, the live schema must exactly match a freshly built one.
    - A newer, edited, extended (extra table, view, trigger, or index), or foreign
      database is refused with `STORAGE_INTEGRITY_FAILED` and left untouched.
  - **Transactions.**
    - Each read or write opens its own connection. Writes use `BEGIN IMMEDIATE`. Reads use
      `query_only`, so a read cannot write.
    - Updates are optimistic: `UPDATE … WHERE id AND batch_id AND created_at AND version =
      expected`. When no row matches, the result is `RecordNotFoundError` or
      `ConcurrentUpdateError`.
  - **Rows are rebuilt through the domain constructors.** A tampered or impossible row
    fails closed as `STORAGE_INTEGRITY_FAILED`.
  - **`compact()`** runs `wal_checkpoint(TRUNCATE)` after deletions, so purged rows do not
    linger in the WAL.
- **Application `application/jobs.py` (`JobService`).** It depends only on ports and the
  domain, receives the clock and the ID factory by injection, and runs each change as one
  transaction.
  - **Commands:**
    - batches: `create_batch`, `set_mask_salary`, `start_batch`, `purge_batch`;
    - documents: `add_document`, `remove_document`, `record_upload`, `reject_upload`,
      `cancel_document`;
    - reviews: `approve_review`, `deny_review`;
    - processing stages: `apply(document_id, transition)`;
    - storage: `reconcile_storage`.
  - **Files follow the record.**
    - A document's input is deleted when the document reaches a terminal state.
    - Its output is deleted when the document ends `FAILED`, `REJECTED`, or `CANCELLED`, or
      when `output_ref` changes (requeue).
    - Deletion after a commit is best-effort; a failure is logged by code and left to
      reconcile.
  - **Remove and purge delete files first, then rows.** If a file cannot be deleted, the
    rows stay and the operation can be repeated (fail closed). Purge deletes the batch row
    and every document row, count, and code, with no tombstone (D-25).
  - **Reconcile (D-26)** deletes files no document needs any more, and unreferenced files
    older than `ORPHAN_GRACE` (1 h). Stage 12 will schedule it.
  - **Batch auto-finish.** A RUNNING batch becomes FINISHED once all its documents are
    terminal or in review.
  - **Timestamps** never go backwards. Each change uses the clock time, or the record's
    `updated_at` if that is later. The clock must return UTC.
- **Test layout.** Fixtures are merged into one `tests/conftest.py`. mypy treats each
  `conftest.py` as the same top-level module, so separate files in `storage/`, `metadata/`,
  and `application/` failed type-checking. `tests/application` was added to pytest's
  `pythonpath`.

## Files added/changed

Added:
- `backend/src/cv_masking/ports/{metadata,clock}.py`
- `backend/src/cv_masking/adapters/clock.py`
- `backend/src/cv_masking/adapters/sqlite/{__init__,migrations,rows,store}.py`
- `backend/src/cv_masking/application/{__init__,jobs}.py`
- `backend/tests/conftest.py`
- `backend/tests/metadata/{test_schema,test_migrations,test_database_files,test_repository}.py`
- `backend/tests/application/{service_helpers,test_job_service,test_concurrency,test_no_pii_persisted}.py`
- `docs/stage-handoffs/stage-4.md`

Changed:
- **Storage:**
  - `ports/storage.py`: `ObjectListing` and `ObjectStore.list_objects`.
  - `adapters/local_storage/stores.py`: implements `list_objects`.
  - `adapters/local_storage/root.py` and `__init__.py`: `METADATA_DIR`, `metadata_path`, and
    `open_metadata()`.
- **Test configuration:** `backend/pyproject.toml` adds `tests/application` to pytest's
  `pythonpath`.
- **Trimmed tests:** every existing test module under `tests/domain`, `tests/storage`,
  `tests/architecture`, and `tests/repo`, plus `tests/test_{config,entrypoint,health}.py`.
  `tests/storage/conftest.py` was removed and merged into `tests/conftest.py`.
- **Docs:**
  - `docs/data-retention.md`: database location and rules, the file layout, the retention
    row, and the reconcile and purge triggers.
  - `docs/product-scope.md`: D-25 and D-26.
  - `THREAT_MODEL.md`: database location; residual risk 14.
  - `docs/stage-plan.md`: Stage 4 status. `README.md`: status line.

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `89 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `68 files already formatted` / `All checks passed!` |
| `npm run format:check`, `npm run lint` | pass |
| `mypy` (strict) | `Success: no issues found in 67 source files` |
| `pytest` | `150 passed` (before trimming: 919) |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

Mutation check. Two bugs were planted one at a time, and the full suite was run after each.
Both were caught, and the files were restored (`150 passed` afterwards):

| Planted bug | Tests failed |
|---|---|
| Drop the `version = ?` condition from updates | 13 |
| Keep the output when verification fails | 1 |

## Tests added

The Stage 4 tests number 53:

- **Metadata, schema (2):** tables and columns are exactly an allowlist of INTEGER and TEXT
  columns. Every text column refuses a synthetic Vietnamese name and address.
- **Metadata, migrations (6):**
  - a new database reaches the latest version in WAL mode with the expected schema;
  - the released checksum is pinned;
  - a newer version, an edited checksum, or an extra table is refused;
  - a foreign database is refused and left untouched.
- **Metadata, files (3):** the folder is `0700` and the database `0600`; a symlinked
  database is refused; the sweeper never touches the database.
- **Metadata, repository (19):**
  - every document state saves and loads unchanged;
  - a stale update is a conflict and changes nothing;
  - a failed transaction writes nothing;
  - deleting a batch removes every row about it;
  - object uses report which files are still needed;
  - four kinds of tampered row fail closed.
- **Application, job service (8):**
  - a full lifecycle finishes the batch and keeps only the output;
  - a failed verification deletes the output, and a requeue deletes the abandoned output;
  - a deletion that fails after a commit is recovered by reconcile;
  - documents can be removed only while the batch is open;
  - purge deletes every file and row of that batch only, and fails closed if a file cannot
    be deleted;
  - reconcile removes only old, unreferenced files.
- **Application, concurrency (1):** of 8 threads cancelling with the same version, exactly
  one wins.
- **Application, no PII persisted (3):**
  - after a full synthetic lifecycle, the database and WAL bytes contain no content markers
    (the hash is present, which proves the scan works);
  - after purge, neither the hash nor the batch ID remains in the database files;
  - log lines contain only IDs, states, counts, and allowlisted words.
- **Storage (1):** `list_objects` reports only regular stored objects. Symlinks and stray
  files are skipped.
- **Architecture (4 in total):**
  - ports and the application layer import only the standard library, the domain, and the
    ports (and not `sqlite3`);
  - adapters import neither the API nor the application layer;
  - only `adapters/sqlite` imports `sqlite3`;
  - there are no subprocess or socket imports.

**What the trim removed from earlier stages.** Small parametrized variants were folded into
single looping tests, and edge cases that the remaining tests already cover were dropped.
The kept tests cover:
- the full transition matrix;
- the random-sequence property test;
- the field allowlist, and errors that never echo values;
- mandatory masks;
- storage path, symlink, overwrite, and cleanup safety;
- sweeper retention;
- loopback-only binding;
- the file guard's main refusals.

## Security/privacy review

- **No new dependencies.** `sqlite3` is in the standard library. There is no subprocess,
  network, or native code. `pytest-socket` still blocks network access in tests.
- **Nothing identifying is stored.** The schema has no place for filenames, text, entity
  values, page images, or exception details, and CHECK constraints refuse free text in
  every text column. The only document-derived value is the input's SHA-256. It is never
  logged, and it is deleted when the batch is purged.
- **Logs.** Services log IDs, states, versions, counts, and codes only. A test enforces a
  token allowlist.
- **Fail closed.**
  - Corrupt, foreign, newer, edited, or extended databases are refused, and so are
    tampered rows.
  - An unsafe database file (symlink, hard link, wrong owner, loose mode) is refused.
  - A file that cannot be deleted blocks the purge.
- **Test data.** Everything is synthetic, in pytest temp directories. The agent never read,
  listed, or searched `data/`, and the ignored-files check filtered only tool caches.

## Known limitations

- **No automatic reopening.** A FINISHED batch is not set back to RUNNING when an approved
  review requeues a document. Stage 12, which owns the queue, has to decide this.
- **Reconcile is not scheduled.** Stage 12 runs it with the sweeper.
- **Old copies can survive.** `secure_delete` zeroes purged rows in the live file. APFS
  snapshots and Time Machine copies taken earlier are unaffected (residual risk 14).
- **One process.** The busy timeout is 5 s, and the design assumes one app process with a
  few worker threads.
- **The unused `PURGED` batch state.** The domain still has it, but purge deletes the row
  instead of storing that state. Nothing reads it.

## Manual verification steps

1. `make check` passes with 150 backend tests and 7 frontend tests.
2. `cd backend && uv run --locked pytest -q tests/metadata tests/application` runs the
   Stage 4 tests.
3. Optional smoke test, using only a throwaway root under `/tmp`:
   ```bash
   cd backend && uv run --locked python -c "
   from pathlib import Path; import tempfile
   from cv_masking.adapters.local_storage import StorageRoot, LocalInputStore, LocalOutputStore
   from cv_masking.adapters.sqlite import SqliteMetadataStore
   from cv_masking.adapters.clock import SystemClock
   from cv_masking.application import JobService
   r = StorageRoot.prepare(Path(tempfile.mkdtemp()) / 'data')
   s = JobService(SqliteMetadataStore.open(r), LocalInputStore(r), LocalOutputStore(r), SystemClock())
   b = s.create_batch(); d = s.add_document(b.batch_id)
   print(r.path, s.get_batch(b.batch_id).document_count); s.purge_batch(b.batch_id)"
   ls -l <printed path>/metadata    # expect -rw------- jobs.sqlite3
   ```
4. On the bank laptop, once the app has created `data/`, run `ls -l data/metadata` and
   expect `-rw-------` for `jobs.sqlite3`.

## Questions/decisions for the tech lead

1. **Requeue after FINISHED.** Answered after the commit (D-27): the batch returns to RUNNING
   and finishes again once the requeued document is settled. Stage 12 implements it.
2. **The trimmed suite.** Confirmed as good enough for the PoC.

## Suggested commit message

```text
feat(metadata): SQLite job metadata and batch/document services (Stage 4)

- Hardened SQLite store in data/metadata (0600, STRICT, CHECKs refuse free text)
- Checksummed migrations; unknown/newer/edited/extended schemas fail closed
- Optimistic, atomic transitions; tampered rows fail closed
- JobService: files follow the record, purge deletes everything, reconcile orphans
- Trim the test suite to essential tests (919 -> 150); merge conftests
- Docs: D-25, D-26, retention, threat model
```
