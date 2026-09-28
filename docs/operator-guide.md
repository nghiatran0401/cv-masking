# Operator guide (HR)

This PoC runs only on the HR user's **macOS** laptop, bound to
`127.0.0.1`. It does not anonymize. Employers, schools, titles, and dates
remain. Embedded photos and images are **not** masked (D-13).

Install and first launch: [install.md](install.md). Troubleshooting:
[troubleshooting.md](troubleshooting.md).

## Start and stop

1. Quit any developer `make dev` session on port 8765.
2. Double-click `scripts/cv-masking.command` (unsigned: first time, Finder
   → right-click → Open).
3. The default browser opens `http://127.0.0.1:8765`. Keep the Terminal
   window open while you work.
4. Stop: close that Terminal window or press Ctrl+C. In-flight work may
   become `JOB_INTERRUPTED`; re-upload those files. Files already stored
   under `data/` stay until you delete them (D-24).

Do not use this app from another device. Do not paste CVs into email
drafts inside the UI (there is no such field) or into ChatGPT/Cursor.

## Process a batch

1. Create a batch. The salary toggle defaults **on** (salary is masked).
   Change it only before you start the batch; it locks once processing
   starts.
2. Drop PDF and DOCX CVs (up to 50 files, 20 MB each, 30 PDF pages).
   Legacy `.doc`, macros, and templates are refused.
3. Start the batch. One document runs at a time. Status is codes and
   per-type counts only — never the candidate's text.
4. When a row is `COMPLETED`, download `redacted-<uuid>.pdf` or
   `.docx`. The ZIP export holds completed files plus a metadata-only CSV
   (ids, statuses, codes, counts). Original filenames stay in this browser
   tab only.
5. `REVIEW_REQUIRED`: open the masked file if a download is offered. Keep
   (approve → `COMPLETED`) only when every reason is a findings reason and
   verification already passed. Deny deletes the output. Blocking reasons
   (encrypted, image-only, no text) are delete-only.
6. Delete the batch in the app when you no longer need the outputs, or
   quit and delete the project `data/` folder. Deletion is not forensic
   erasure; FileVault is assumed.

## What "done" means

- `COMPLETED` means independent verification passed on a new file. The
  input copy is then deleted; the output stays until you delete it.
- Hidden content is always removed. You see kind and count, not the hidden
  text.
- A failed file does not fail the rest of the batch.

## What you must still check

- Photos, logos, and screenshots in the file (unmasked).
- Career history that still identifies the person.
- Names the detectors missed (especially unusual layouts). The UI may
  flag `DETECT_NO_CANDIDATE_NAME` for that.
- Short or generic words (gender, ethnicity tokens) that verification
  does not search everywhere.

## Evaluation

`make eval` prints a metadata-only report on synthetic files (no real CVs).
Never give real CVs to Cursor or any AI tool. An authorized local run, if
ever needed, is described in [SECURITY.md](../SECURITY.md) §2.
