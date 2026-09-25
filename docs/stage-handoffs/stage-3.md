# Stage 3 handoff — Local storage and cleanup

## Stage and objective

Stage 3 adds safe local file storage for uploaded inputs, masked outputs, and per-attempt
work directories, plus a file-age sweeper. All storage lives under a dedicated per-user root
outside the repository (`~/Library/Caches/CVMasking`). There is still no API, metadata,
or document processing; nothing calls the storage from the running app yet.

## Architecture decisions

- **Ports, then adapters.** `cv_masking.ports.storage` defines narrow Protocols
  (`InputStore`, `OutputStore`, `WorkArea`, `StorageSweeper`) and the value types
  `StoredObject` and `SweepReport`, using only the standard library and the domain. The
  adapter is `cv_masking.adapters.local_storage`. Architecture tests enforce this
  direction.
- **Producer-based writes.** `ObjectStore.save(fmt, producer, *, max_bytes)` hands the
  producer a size-limited sink. Callers can stream output without the store ever holding a
  full path or raw text. `InputStore.save_stream` wraps an iterable of chunks for uploads.
  The sink hashes (SHA-256) and counts bytes as they arrive.
- **Descriptor-relative filesystem access.** Every operation goes through an open
  directory fd with `O_NOFOLLOW | O_DIRECTORY | O_CLOEXEC`, using `dir_fd=` calls. There is
  no string path joining at use time. This is why the adapter package has a Ruff `PTH`
  per-file ignore: pathlib has no `dir_fd`/`O_NOFOLLOW` equivalents.
- **Never overwrite.** Final names are created by `os.link` from a hidden temp file, which
  fails if the name exists, instead of `rename`, which would replace the existing file.
- **Fail closed.** Any unexpected `OSError` becomes a `StorageError` with a closed code
  (`STORAGE_WRITE_FAILED`, `STORAGE_PATH_REJECTED`, `STORAGE_INTEGRITY_FAILED`,
  `UPLOAD_FILE_TOO_LARGE`). A missing or tampered object is `STORAGE_INTEGRITY_FAILED`.
- **Domain change (approved):** `DocumentJob` gained `input_ref: ObjectRef | None`, set by
  `mark_uploaded(..., input_ref=...)`. A new invariant makes `output_ref` differ from
  `input_ref`, so a document's input and output can never share a storage name.
- **Root claim rule.** A root is adopted only if it is new, empty, or already carries the
  `.cv-masking-cache` marker. The root is refused if it is:
  - inside a git checkout;
  - relative;
  - owned by another user;
  - a symlink.
  Loose permissions on a user-owned root are tightened to `0700`, and a warning is logged.
- **Backups and indexing (approved):** the app relies on Time Machine's standard exclusion
  of `~/Library/Caches` (confirmed with `tmutil isexcluded` on the development Mac) and
  writes a `.metadata_never_index` marker. No subprocess and no native calls are used.
  Manual checks are in `docs/data-retention.md` §3.
- **Sweeper thresholds (approved):** stored objects are removed after 24 h even with no
  metadata. Temp files, work directories and unexpected entries are removed after 1 h.
  The sweeper never follows symlinks, never touches the root's own markers, and logs only
  counts.

## Files added/changed

Added:
- `backend/src/cv_masking/ports/__init__.py`, `ports/storage.py`
- `backend/src/cv_masking/adapters/__init__.py`
- `backend/src/cv_masking/adapters/local_storage/{__init__,root,stores,work_area,sweeper}.py`
- `backend/tests/storage/{conftest,test_cache_root,test_object_stores,test_work_area,test_sweeper,test_storage_logging}.py`
- `backend/tests/architecture/test_layer_boundaries.py`
- `docs/stage-handoffs/stage-3.md`

Changed:
- `backend/src/cv_masking/domain/document_job.py`: `input_ref` and the new invariant.
- `backend/tests/domain/{domain_builders,test_document_guards,test_document_invariants,test_document_properties,test_document_transitions,test_no_pii_fields}.py`: updated for `input_ref`.
- `backend/pyproject.toml`: Ruff `PTH` per-file ignore for `adapters/local_storage/**`.
- `docs/data-retention.md`: file layout, root rules, Time Machine and Spotlight findings, manual checks, sweeper thresholds.
- `docs/stage-plan.md` (Stage 3 status), `README.md` (status line).

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `73 file(s) checked, none refused.` |
| `ruff format --check .` | `51 files already formatted` |
| `ruff check .` | `All checks passed!` |
| `npm run format:check`, `npm run lint` | pass |
| `mypy` (strict) | `Success: no issues found in 50 source files` |
| `npm run typecheck` | pass |
| `pytest` | `871 passed` (Stage 2 follow-up: 718) |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |
| `tmutil isexcluded ~/Library/Caches` | `[Excluded]` |

Mutation check. Five bugs were planted one at a time in the storage adapter, and the
storage tests were run after each. Every bug was caught, and all files were restored:

| Planted bug | Tests failed |
|---|---|
| Drop `O_NOFOLLOW` when opening an object | 2 |
| Use `rename` instead of `link` (allows overwrite) | 2 |
| Adopt a non-empty, unmarked root directory | 1 |
| Sweeper follows symlinks when checking age | 1 |
| Skip work-directory cleanup when an attempt fails | 2 |

## Tests added

There are 150 new storage and architecture tests, plus new domain cases:

- **`test_cache_root.py` (20):**
  - creates the root with mode 0700, both markers and the kind directories;
  - is idempotent;
  - adopts an empty existing directory;
  - refuses invalid paths, a missing parent, a file or symlink at the root, a root owned by another user, a root inside a git checkout, a non-empty unmarked directory, and a marker that is not a file;
  - tightens loose permissions;
  - refuses a kind directory that is later missing, symlinked, or loosened.
- **`test_object_stores.py` (76, over both stores):**
  - round-trip, hash, size, mode 0400, UUID names, and no temp file left behind;
  - streaming limits (exact limit, over the limit, empty, non-bytes chunks, invalid `max_bytes`);
  - a failing producer, an interrupted stream, or a full disk leaves nothing behind;
  - a failure after linking removes the final object;
  - never overwrites on a name collision;
  - a missing object, a tampered object, a wrong record, and a symlink, hard link, directory, FIFO (without blocking), or world-readable object at an object name;
  - untyped refs and formats; the format is part of the address;
  - `delete` is idempotent and removes a planted symlink without following it.
- **`test_work_area.py` (8):**
  - a unique 0700 directory per attempt;
  - removal after success and after failure;
  - an unsafe or swapped work directory fails closed and is never followed; the outside file is untouched;
  - a cleanup failure during an error keeps the original error and defers to the sweeper.
- **`test_sweeper.py` (10):**
  - age thresholds for every category, including the 24 h retention window;
  - future mtimes are kept;
  - symlinks are removed, never followed, and an outside file survives;
  - root markers are untouched;
  - removal failures are counted;
  - a non-UTC `now` is rejected.
- **`test_storage_logging.py` (1):** full lifecycle logs contain only allowlisted tokens and no synthetic content, root path, or filename.
- **`test_layer_boundaries.py` (35):**
  - ports import only the standard library and the domain;
  - adapters don't import FastAPI, Starlette, Uvicorn, Pydantic, or the API layer;
  - no source module imports subprocess, socket, `urllib.request`, `http.client`, ftplib, or smtplib.
- **Domain:**
  - an upload without `input_ref` is rejected;
  - a raw UUID as `input_ref` is rejected;
  - an output cannot reuse the input ref;
  - `EXPECTED_FIELDS` includes `input_ref`.

## Security/privacy review

- **No new dependencies.** No subprocess, ctypes, or network code in production. Test subprocess use is unchanged from Stage 2. `pytest-socket` still blocks network access in tests.
- **Logs** carry only the store kind, random object UUIDs, counts, and codes. They never contain paths, filenames, content, or hashes. A test enforces this.
- **Stored files:**
  - no original filename, no candidate data in any name;
  - owner-only permissions;
  - the input and output of a document use different identifiers.
- **Traversal and symlink attacks** are blocked by descriptor-relative access with `O_NOFOLLOW`, strict name patterns, and `fstat` ownership, link-count, and mode checks. The sweeper uses `lstat` and a symlink-safe `rmtree` with a directory fd.
- **Test data:** all fixtures are synthetic byte strings in pytest temp directories. No real CV was read. No runtime directory outside the repository was read or created by the agent. The `tmutil` query checked only exclusion status.
- **Working tree:** `git status` shows only source, test, and doc files. The ignored entries are tool caches.

## Known limitations

- **Orphan cleanup by metadata** ("file with no matching row") needs Stage 4. Until then, only age-based removal exists.
- **The sweeper is not scheduled yet.** It runs every 10 minutes and at startup once the queue exists (Stage 12).
- **Future mtimes** (clock moved back) are kept until the clock passes them.
- **The root path is resolved once** at `prepare`. Replacing the root directory itself while the app runs is outside this stage's threat scope, because a local attacker with the user's privileges is excluded by assumption A-2.
- **Spotlight's `.metadata_never_index`** on a folder is best-effort. The manual `mdfind` check must be run on the bank image.
- **Time Machine exclusion** relies on the system's standard exclusions. Bank backup or DLP agents may still copy the files (A-3).
- **No Windows handling** (D-08).
- **Deletion is unlink under FileVault.** There is no forensic erasure (A-1).

## Manual verification steps

1. `make check` passes, with 871 backend tests.
2. `cd backend && uv run --locked pytest -q tests/storage tests/architecture`: 150 new tests plus the existing domain-boundary tests pass.
3. Optional, on a Mac, using only a throwaway root under `/tmp`:
   ```bash
   cd backend && uv run --locked python -c "
   from pathlib import Path; import tempfile
   from cv_masking.adapters.local_storage import CacheRoot, LocalInputStore
   from cv_masking.domain.formats import DocumentFormat
   r = CacheRoot.prepare(Path(tempfile.mkdtemp()) / 'cache')
   s = LocalInputStore(r).save_stream(DocumentFormat.PDF, [b'synthetic'], max_bytes=100)
   print(r.path, s.ref, s.size_bytes)"
   ls -la <printed path>/inputs    # expect -r-------- <uuid>.pdf
   ```
4. On a bank laptop, once later stages create the real root, run the three checks in `docs/data-retention.md` §3.

## Questions/decisions for the tech lead

1. **Spotlight:** if the `mdfind` check shows the folder is indexed on the bank image, should Stage 14 add an explicit exclusion? That would need a documented subprocess or native call.
2. **Q-07** (should quitting erase everything?) is still open. It affects Stage 15, not this stage.

## Suggested commit message

```text
feat(storage): local file storage, work areas, and sweeper (Stage 3)

- Storage ports and a dir_fd/O_NOFOLLOW local adapter under ~/Library/Caches/CVMasking
- Atomic, size-limited, hashed, non-overwriting writes; 0400 objects, 0700 dirs
- Per-attempt work directories removed on success and failure
- Age-based sweeper (24 h objects, 1 h temp/work/unexpected), symlink-safe
- DocumentJob.input_ref with output_ref != input_ref invariant
- Retention docs: layout, Time Machine/Spotlight findings, manual checks
```

---

## Follow-up: in-project storage and manual deletion

Everything above describes the Stage 3 commit (`0a3cc11`). After review, the tech lead
changed three decisions and accepted the stated risks:

- **D-22:** runtime files live in `<project>/data/`.
- **D-23:** stored inputs and outputs are never deleted by age.
- **D-24:** quitting does not erase anything (answers Q-07).

The Spotlight manual check was dropped as unnecessary.

### Changes

- **Location.**
  - `default_storage_root()` returns `<project>/data`.
  - `CacheRoot` is renamed to `StorageRoot`, and the marker is renamed to `.cv-masking-data`.
  - The rule refusing a root inside a git checkout is removed. The other root rules are unchanged: absolute path, owner, no symlink, marker or empty directory, and `0700`.
- **Kept out of git and Cursor.** `data/` was already in `.gitignore` and `.cursorignore`, so no protected-file edit was needed.
  - New tests fail if either entry is removed.
  - The file guard now refuses any staged path under `data/`, whatever its name or content, even a `synthetic-*` fixture. The rule is anchored at the repository root.
- **Retention.** The sweeper keeps stored `inputs/` and `outputs/` objects forever, and `SweepReport.expired` is removed.
  - Temp files, work directories, and unexpected entries are still removed after 1 h.
  - Work directories are still deleted after every attempt.
- **Domain.** `DocumentJob.expire`, `RETENTION_WINDOW`, and `ErrorCode.JOB_EXPIRED` are removed (D-19 superseded). A document in review now waits for HR.
- **Docs.**
  - `AGENTS.md`: agents must never read, list, or search `data/`.
  - `SECURITY.md`: real CVs may be in the checkout only in `data/`, written by the app; exclude `data/` from Time Machine by hand.
  - `THREAT_MODEL.md`: TB-D updated; residual risks 11–13 added.
  - `data-retention.md` §3–§5; `error-codes.md`; `product-scope.md` (D-06 and D-19 superseded, D-22 to D-24 added); a Stage 3 follow-up note in `stage-plan.md`.

### Commands and results

| Command | Result |
|---|---|
| `make check` | exit 0 |
| file guard `--all` | `89 file(s) checked, none refused.` |
| `ruff format --check .` / `ruff check .` | `51 files already formatted` / `All checks passed!` |
| `mypy` | `Success: no issues found in 50 source files` |
| `pytest` | `861 passed` (10 fewer than the commit: the expiry tests were removed and new tests added) |
| `vitest run` | `7 passed (7)` |
| `git check-ignore -v data/inputs/x.pdf` | `.gitignore:9:data/` |

Mutation check. Three bugs were planted one at a time; each was caught, and all files were restored:

| Planted bug | Tests failed |
|---|---|
| Sweeper removes old stored objects | 1 |
| File guard no longer blocks `data/` | 3 |
| `data/` removed from `.gitignore` | 1 |

### Tests added or changed

- **Added:**
  - the default root is `<project>/data`;
  - `data/` is listed in `.gitignore` and `.cursorignore`;
  - a root inside a project checkout is allowed;
  - stored objects a year old are kept;
  - the guard refuses three kinds of `data/` paths and allows a nested `.../data/` source directory.
- **Removed:** the git-checkout refusal tests, the `expire` guard, transition, and property cases, and the 24 h sweeper test.
- **Retargeted:** the sweeper failure-counting and future-timestamp tests now use temp files instead of stored objects.

### Accepted risks (tech lead)

- **Cursor can reach real CVs.** They sit inside the Cursor workspace, and `.cursorignore` is best-effort. An agent's terminal command could still read `data/`.
- **Backups.** Time Machine backs up `data/` until you run `tmutil addexclusion <project>/data`. The app does not do this, because it runs no subprocesses.
- **No automatic expiry.** CVs remain on the laptop until HR deletes them.

### Manual verification

- **Permissions:** after the app first writes files, run `ls -ld data data/inputs` and expect `drwx------`. Run `ls -l data/inputs` and expect `-r--------` for each file.
- **Another account:** `sudo -u <other-user> ls <project>/data` should print "Permission denied".
- **Manual deletion:** quit the app, then run `rm -rf <project>/data`.

### Suggested commit message

```text
feat(storage): keep runtime files in ignored project data/, manual deletion only

- Default storage root is <project>/data (git- and cursor-ignored, refused by file guard)
- Sweeper never removes stored inputs/outputs by age; leftovers still cleared after 1 h
- Remove DocumentJob.expire, RETENTION_WINDOW, and JOB_EXPIRED
- Decisions D-22 to D-24; SECURITY, THREAT_MODEL, AGENTS, retention docs updated
```
