# Privacy assumptions, local retention, and cleanup

Runtime files live in the project's `data/` folder (D-22–D-26, D-33). The
evaluation harness does not write there. Uninstall is documented in
[install.md](install.md).

## 1. Privacy assumptions

These must hold for the privacy claims of this tool to be true. If any is false,
the claim in the README does not apply.

| ID | Assumption |
|---|---|
| A-1 | The laptop is bank-managed, with full-disk encryption (FileVault) enabled. Deletion relies on FDE; we do not claim forensic erasure (SSDs do not guarantee overwrite). |
| A-2 | The HR user's OS account is not shared, and no untrusted local users or malware have access. A local attacker with the user's privileges can read everything the app can. |
| A-3 | Bank endpoint agents (backup, DLP, EDR) may copy files from the user profile. This is outside the app's control and must be assessed by bank security. |
| A-4 | The browser is a bank-approved browser. Extensions with "read all sites" permission can read `http://127.0.0.1` pages; the app cannot prevent this. |
| A-5 | The original CV already exists on the laptop (email attachment, download folder). The app does not manage or delete the user's original copy. |
| A-6 | Developers never have access to real CVs. Cursor and any AI assistant only ever see synthetic data. |

## 2. What "local" protects and what it does not

Protected by design:
- CV bytes, extracted text, and detected values are never sent over any network.
- No cloud processing, telemetry, crash reporting, or remote model inference.
- A second device on the LAN cannot connect (loopback bind + Host/Origin checks).

**Not** protected by "local":
- **Browser uploads create copies.** The browser reads the file and sends it to the local
  server, which stores a working copy. Large request bodies may be spooled to disk by the
  browser or server. The app manages its own copies (below); it cannot manage browser internals.
- **Downloads leave the app's control.** Masked outputs saved to Downloads follow the user's
  normal file handling (sync clients, email, backups).
- **Swap and hibernation.** Process memory holding transient text may be paged to disk; FDE is
  the mitigation (A-1).
- **Cursor prompts leave the machine.** Anything pasted into Cursor chat, attached, or read by
  the agent is sent for model inference. `.cursorignore` is best-effort only.
- **Masking is not anonymization.** Outputs can still identify a person through career history.

## 3. Storage locations

All runtime files live in the project's `data/` folder (decision D-22):

| Platform | Location |
|---|---|
| macOS | `<project>/data/` (files and the SQLite metadata database `data/metadata/jobs.sqlite3`) |
| Windows | Future stage (D-08) |

File layout (Stages 3 and 4):

```text
<project>/data/                      0700, owned by the HR user
  .cv-masking-data                   0600 marker: this directory belongs to the app
  .metadata_never_index              0600 marker: ask Spotlight not to index
  inputs/<uuid4>.pdf|.docx           0400 uploaded copies
  outputs/<uuid4>.pdf|.docx          0400 masked outputs
  work/<uuid4>/                      0700 one directory per upload or processing attempt
  logs/                              0700 rotated application logs (IDs and codes only)
    app.log                          0600
  lock/                              0700 single-instance lock
    instance.lock                    0600 pid; flock exclusive
  metadata/                          0700 never swept
    jobs.sqlite3 (+ -wal, -shm)      0600 job metadata (no document content)
```

Rules:
- Directories are owner-only (`0700`); stored objects are read-only to the owner (`0400`).
- Every server-side path is `<root>/<kind>/<random-uuid>[.pdf|.docx]`, with the extension
  taken from the validated format. Original filenames are never
  used in any path, database row, log line, or report. The input and output of a
  document use different random identifiers.
- **Kept out of git and Cursor.** `data/` is listed in `.gitignore` and `.cursorignore`
  (a test fails if either entry is removed), and the file guard refuses any staged path
  under `data/`, whatever its type. `.cursorignore` is best-effort: an agent's terminal
  command can still read the folder. Agents must never read `data/` (AGENTS.md).
- **Dedicated root.** The root must be an absolute path. An existing non-empty directory
  without the `.cv-masking-data` marker is refused (the app never adopts, sweeps, or
  deletes a directory it did not create). A root owned by another user, or a symlink, is
  refused. A root owned by the user with looser permissions is tightened to `0700` and a
  warning is logged.
- **No path traversal or symlinks.** Every file operation is relative to an already-opened
  directory descriptor with `O_NOFOLLOW`. Names are generated internally and checked against
  a strict pattern. An opened object must be a regular file, owned by the user, with a
  single link and no group/other permissions; otherwise it is refused.
- **Atomic, non-overwriting writes.** Data goes to a hidden `.<random>.part` temp file in
  the same directory, which is size-limited while streaming, hashed, fsynced, made
  read-only, then hard-linked to its final name (a link never replaces an existing file),
  and the directory is fsynced. A partial file is never visible under a final name, and
  no input or output is ever overwritten.
- **Metadata database.** `metadata/jobs.sqlite3` holds only random IDs, states, versions,
  timestamps, sizes, SHA-256 hashes, finding counts per entity type, closed error and review
  codes, and software versions. There is no column for filenames, text, entity values, or
  exception details, and every text column has a CHECK constraint that refuses free text
  (a test writes a synthetic name and address into each one). The file is created `0600`
  without following symlinks; the app refuses to open it (or its `-wal`/`-shm` files) if it
  is a symlink, a hard link, owned by someone else, or readable by others. It uses
  `secure_delete` (deleted rows are zeroed) and truncates the WAL after every deletion. An
  unknown, newer, edited, or extended schema is refused rather than adopted or migrated.
- **Time Machine backs up `data/` by default.** Unlike `~/Library/Caches`, a project
  folder is included in backups, so deleted CVs could survive on the backup disk. Exclude
  it once by hand (the app runs no subprocess): `tmutil addexclusion <project>/data`.
  Bank backup agents may ignore this (A-3).
- **Spotlight.** The app writes a `.metadata_never_index` marker in the root. Its effect on
  a folder is best-effort. Stored files have no filename metadata beyond a UUID.

Checks (after the app has created the folder):

```bash
ls -ld data data/inputs            # expect drwx------ <hr-user>
ls -l data/inputs data/outputs     # expect -r-------- <hr-user> for each file
ls -l data/metadata                # expect -rw------- <hr-user> jobs.sqlite3
tmutil isexcluded data             # expect [Excluded] after tmutil addexclusion
git check-ignore data/x            # expect: data/x (ignored)
```

To prove another account cannot read it: `sudo -u <other-user> ls <project>/data` should
print "Permission denied". Administrators, root, and bank security agents are not stopped
by file permissions (A-2, A-3).

## 4. Retention schedule

| Data | Where | Deleted when (whichever first) |
|---|---|---|
| Uploaded input copy | data/inputs | Document reaches a terminal state (`COMPLETED`, `FAILED`, `REJECTED`, `CANCELLED`); or HR deletes the document/batch. A document in `REVIEW_REQUIRED` keeps its input until HR decides. |
| Work/intermediate files | data/work | End of each upload identification or processing attempt (success or failure). |
| Masked output | data/outputs | HR deletes it (in the app, or by deleting the folder). **No automatic expiry** (D-23). |
| ZIP export (API) | Temporary `export.zip` in `data/work/<uuid>/` | Deleted when the download response finishes (the work directory is closed in a background task). If the process dies first, the sweeper removes the work directory after 1 h. There is no `data/exports` directory. The HR **Tải tất cả CV đã che** ZIP (`output.zip`) is built in the browser, may include original File bytes from this tab, and is not stored under `data/`. |
| CSV report (metadata only) | Generated on demand, not stored | — |
| Evaluation JSON/Markdown (counts only) | stdout of `make eval`; not stored by the app | — |
| SQLite job metadata (IDs, states, counts, hashes, codes, timestamps) | data/metadata/jobs.sqlite3 | HR purges the batch: the batch row and every document row, count, and code are deleted, with no tombstone (D-11, D-25). Removing a document from an open batch deletes its rows. |
| Logs (metadata only: IDs, codes, counts, durations) | `data/logs/app.log` (10 MiB, 7 backups) | Rotated; leftover files stay until HR deletes `data/`. |
| Original filenames (display and download names) | Browser tab memory | Tab closed or reloaded. Never written to disk by the server. |
| Pasted CV source URLs | Browser tab memory | Tab closed, reloaded, new batch, or purge. Never sent to the API. |
| Extracted text, detected values, decompressed DOCX parts | Worker process memory | Dropped when the document's verification ends, or when the worker process is ended (timeout, crash, shutdown); never written to disk by the app. |

There is no age-based deletion of inputs or outputs (D-23). HR is responsible for deleting
them; to erase everything by hand, quit the app and delete `<project>/data/`.

## 5. Cleanup triggers

1. **Per job (Stage 12):** the worker process only reads stored files and returns the
   redacted output as bytes; the API process stores it (temp file, then atomic rename).
   A document that fails after its output was stored has the output deleted in the same
   step. A worker ended mid-document (timeout, crash) therefore leaves no files; a temp
   file left by a crash of the API process is removed by the sweeper.
2. **Terminal state:** input copy deleted immediately.
3. **Periodic sweeper:** every 10 minutes while running, removes crash leftovers. It exists
   since Stage 3 and is scheduled since Stage 12 (at startup, then every 10 minutes). It looks only inside `inputs/`,
   `outputs/` and `work/`, never follows symlinks, and removes by file age:

   | Entry | Removed after |
   |---|---|
   | `inputs/` or `outputs/` object (`<uuid4>.pdf/.docx`) | Never (HR deletes, D-23) |
   | Temp file (`.<hex>.part`) | 1 h |
   | Work directory (`work/<uuid4>`) | 1 h |
   | Anything else (unexpected names, symlinks, stray directories) | 1 h |

   Timestamps in the future are left alone. Each run logs only counts; a failure
   to remove an entry is counted and retried on the next run.
4. **Startup (Stage 12):** before accepting requests, documents a previous run left
   mid-processing (`VALIDATING`, `PROCESSING`, `VERIFYING`) are failed with the retryable
   `JOB_INTERRUPTED` (D-33; no automatic re-run, HR clicks **Thử lại**), then the sweeper and
   reconcile run. Documents still `UPLOADED` in a running batch simply wait in the queue.
5. **Reconcile (Stage 4 service, scheduled in Stage 12 with the sweeper, D-26):** compares stored files with
   the metadata. It deletes an input or output that no document needs any more (for example
   when a deletion after a commit failed), and a file with no metadata row once it is older
   than 1 h (a younger one may be an upload still being recorded).
6. **Batch purge:** deletes the batch's files first, then its rows; if a file cannot be
   deleted, the rows stay and the purge can be repeated.
7. **HR "Clear all":** deletes every batch, file, and metadata row immediately.
8. **Graceful shutdown (Stage 12):** the document in progress gets up to 10 seconds to
   finish; otherwise the worker process is ended and the document fails with
   `JOB_INTERRUPTED` (its input and any output are deleted as for any terminal state).
   Waiting documents stay `UPLOADED` and are processed after the next start.
   Inputs, outputs, and metadata are otherwise kept (D-24).
9. **Uninstall (Stage 15):** quit the `.command` (or Ctrl+C), then delete the project
   folder. That removes the program, `.venv`, and `data/` (including inputs, outputs,
   metadata, logs, and the instance lock). This is not forensic erasure (A-1). Downloads
   of masked files are not removed. See [install.md](install.md).

## 6. Hash handling

A SHA-256 of each input is stored for duplicate detection and integrity checks.
A hash can confirm whether a known file was processed, so it is treated as
personal metadata: it has the same retention as the job record and is never
logged or included in reports.
