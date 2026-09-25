# Privacy assumptions, local retention, and cleanup

Status: Stage 0 baseline. Storage is implemented in Stage 3, metadata in Stage 4,
recovery in Stage 12, shutdown in Stage 15.

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

All runtime data lives **outside the repository** under a per-user application root:

| Platform | Application root |
|---|---|
| macOS | `~/Library/Application Support/CVMasking/` (metadata) and `~/Library/Caches/CVMasking/` (files) |
| Windows | Future stage (D-08); expected `%LOCALAPPDATA%\CVMasking\` |

Rules:
- Directories are created owner-only (`0700`).
- Every server-side path is `<root>/<kind>/<random-uuid>[.pdf|.docx]`, with the extension
  taken from the validated format. Original filenames are never
  used in any path, database row, log line, or report.
- All path resolution is containment-checked against the root; symlinks are refused.
- Writes are atomic (temp file in the same directory, fsync, rename). A partial file is never
  visible under a final name.
- Exclusion from OS indexing and backups (Spotlight, Time Machine) is
  investigated and documented in Stage 3; it is not assumed.

## 4. Retention schedule

| Data | Where | Deleted when (whichever first) |
|---|---|---|
| Uploaded input copy | files/inputs | Document reaches a terminal state (`COMPLETED`, `FAILED`, `REJECTED`, `CANCELLED`); HR deletes the document/batch; **24 h** after upload (a document still in `REVIEW_REQUIRED` at 24 h becomes `FAILED`/expired and its input is deleted). |
| Work/intermediate files | files/work | End of each processing attempt (success or failure). |
| Masked output | files/outputs | HR clears it; **24 h** after the document completed. |
| ZIP export | files/exports | Streamed download finishes, or 1 h after creation. |
| CSV report (metadata only) | Generated on demand, not stored | — |
| SQLite job metadata (IDs, states, counts, hashes, codes, timestamps) | Application Support / LOCALAPPDATA | Batch is purged (all its documents purged). No long-term audit trail (D-11). |
| Logs (metadata only: IDs, codes, counts, durations) | Application log dir | 7 days, 10 MB cap, rotated (proposed). |
| Original filenames (display only) | Browser tab memory | Tab closed or reloaded. |
| Extracted text, detected values, decompressed DOCX parts | Worker process memory | End of the job; never written to disk by the app. |

The 24 h windows are hard maximums; they are not extended by activity.

## 5. Cleanup triggers

1. **Per job:** after every attempt, the worker deletes its work files in a `finally` path
   that cannot be skipped by exceptions; cleanup failure is logged by code and retried by the sweeper.
2. **Terminal state:** input copy deleted immediately.
3. **Periodic sweeper:** every 10 minutes while running, purges anything past §4 windows and
   any orphan file with no matching metadata row.
4. **Startup:** runs the sweeper before accepting requests; documents found mid-processing are
   recovered per Stage 12 (bounded retry) or failed with `JOB_INTERRUPTED`.
5. **HR "Clear all":** deletes every batch, file, and metadata row immediately.
6. **Graceful shutdown:** deletes work files; in-flight jobs return to `QUEUED` for recovery.
   Inputs and outputs remain until their §4 window (open question Q-07: should quit erase everything?).
7. **Uninstall (Stage 15):** documented steps remove the application root entirely.

## 6. Hash handling

A SHA-256 of each input is stored for duplicate detection and integrity checks.
A hash can confirm whether a known file was processed, so it is treated as
personal metadata: it has the same retention as the job record and is never
logged or included in reports.
