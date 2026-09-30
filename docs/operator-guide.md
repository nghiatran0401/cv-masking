# Operator guide (HR)

This PoC runs only on the HR user's **macOS** laptop, bound to
`127.0.0.1`. It does not anonymize. Employers, schools, titles, dates, and
personal URLs remain. Embedded photos and images are **not** masked (D-13).

Install and first launch: [install.md](install.md). Troubleshooting:
[troubleshooting.md](troubleshooting.md).

## Start and stop

1. Quit any developer `make dev` session on port 8765.
2. Double-click `scripts/cv-masking.command` (unsigned: first time, Finder
   → right-click → Open).
3. The default browser opens `http://127.0.0.1:8765`. Keep the Terminal
   window open while you work.
4. Stop: close that Terminal window or press Ctrl+C. In-flight work may
   become `JOB_INTERRUPTED`; click **Thử lại** on those rows. Files already stored
   under `data/` stay until you delete them (D-24).

Do not use this app from another device. Do not paste CVs into email
drafts inside the UI (there is no such field) or into ChatGPT/Cursor.

## Process a batch

1. Create a batch. The salary toggle defaults **on** (salary is masked).
   Change it only before you start the batch; it locks once processing
   starts.
2. Drop PDF and DOCX CVs, or paste up to 50 `https` links from
   `data.ehiring.ehr.vib` and click **Tải các liên kết**. This laptop downloads
   those files and adds them to the batch. The link must open without the
   browser login; if it only works while you are logged in, that file is not
   added and you can save it yourself, then use **Chọn thư mục** or drop.
   Then click **Bắt đầu che**. Up to 50 files, 20 MB each, 30 PDF pages.
   Legacy `.doc`, macros, and templates are refused. **Thử lại** needs the
   file in this tab, so a file that arrived only from a link cannot be retried
   that way; paste the link and click **Tải các liên kết** again.
3. Start the batch. One document runs at a time. Status is codes and
   per-type counts only — never the candidate's text. If a row fails,
   **Thử lại** re-sends that file in this batch (the file must still be in
   this browser tab). Extra new files need a new batch.
4. When a row is `COMPLETED`, **View** opens a masked PDF in the app.
   Word files are download-only (the app never converts formats). Download
   saves `masked_<original filename>`. **Tải tất cả CV đã che** builds
   `output.zip`. Each downloadable candidate is a folder
   `output/candidate <name>/` with the original file and `masked_<name>`,
   including **Cần xem** rows. Files that failed with *Không gỡ được siêu dữ
   liệu hoặc nội dung ẩn* are omitted. Share only the `masked_` files you have
   checked. Original filenames stay in this browser
   tab only; they are not in SQLite or CSV. If a row says leftover
   information remains, **View** is for inspection only — do not share that
   file until you have checked it. The row lists leftover types and pages, never the leftover text.
5. `REVIEW_REQUIRED`: **View** a PDF, or download if a file is offered.
   Keep (approve → `COMPLETED`) only when every reason is a findings
   reason and verification already passed. Deny deletes the output.
   Blocking reasons (encrypted, image-only, no text) are delete-only.
6. Delete the batch in the app when you no longer need the outputs, or
   quit and delete the project `data/` folder. Deletion is not forensic
   erasure; FileVault is assumed.

## What "done" means

- `COMPLETED` means independent verification passed on a new file. The
  input copy is then deleted; the output stays until you delete it.
- Hidden content is always removed. You see kind and count, not the hidden
  text. Designer PDFs (Canva/Figma) with hidden or odd layers are stripped
  in the app; unreadable layer rules are treated as hidden (some decoration
  may disappear). If a file still fails with `REDACT_SANITIZE_FAILED`, save
  a flattened copy from Preview (File → Print → PDF → Save as PDF) and
  upload that.
- A failed file does not fail the rest of the batch.

## What you must still check

- Photos, logos, and screenshots in the file (unmasked).
- Profile, GitHub, LinkedIn, and portfolio URLs (unmasked).
- Career history that still identifies the person.
- Names the detectors missed (especially unusual layouts). The UI may
  flag `DETECT_NO_CANDIDATE_NAME` for that.
- Short or generic words (gender, ethnicity tokens) that verification
  does not search everywhere.

## Evaluation

`make eval` prints a metadata-only report on synthetic files (no real CVs).
Never give real CVs to Cursor or any AI tool. An authorized local run, if
ever needed, is described in [SECURITY.md](../SECURITY.md) §2.
