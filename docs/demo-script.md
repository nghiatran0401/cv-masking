# Demo script (synthetic files only)

Audience: tech lead / HR sponsor on the development Mac (Apple Silicon).
Time: about 10 minutes. **Do not use real CVs. Do not open `data/` in
Cursor.**

## 0. Limits to say out loud

- Masked, not anonymous.
- Photos and image text are not removed (D-13).
- Unsigned launcher; PyMuPDF AGPL not settled.
- Intel Macs untested.
- One malformed file fails; the rest of a batch continues.

## 1. Generate two synthetic CVs

From the repo (prints only a temp directory path):

```bash
cd backend
uv run --locked python -c "
from pathlib import Path
from cv_masking.evaluation.fixtures import annotated_docx, annotated_pdf
out = Path('/tmp/cv-masking-demo')
out.mkdir(parents=True, exist_ok=True)
(out / 'synthetic-cv.pdf').write_bytes(annotated_pdf())
(out / 'synthetic-cv.docx').write_bytes(annotated_docx())
print(out)
"
```

Do not attach these files to Cursor.

## 2. Quality gate and metrics (optional, 2 min)

```bash
make eval          # metadata JSON; no values
# make check       # if you need the full gate; several minutes
```

Point at `photos_and_images_unmasked: true`, separate `pdf` / `docx`
blocks, `failed: 1` on the synthetic set (malformed companion files), and
PDF `family_details` / `reference_name` recall 0 on this labeled PDF
layout.

## 3. HR path (5 min)

1. Quit `make dev` if it is running.
2. Double-click `scripts/cv-masking.command` (or
   `backend/.venv/bin/python -m cv_masking --desktop`).
3. Confirm the UI is Vietnamese at `http://127.0.0.1:8765` (no Vite port).
4. New batch, salary toggle on, drop the two `/tmp/cv-masking-demo`
   files.
5. Start. Show per-document status (codes and counts, no CV text).
6. Download a `COMPLETED` `redacted-<uuid>.…` file. Open it in Preview or
   Word: labeled fields gone; company/dates remain; PDF image still there.
7. If a row is `REVIEW_REQUIRED`, show keep vs delete (D-34).
8. Download ZIP: only completed outputs + metadata CSV.
9. Quit Terminal. Say that `data/` remains until deleted (D-24).

## 4. Failure path (1 min)

Upload a renamed text file or a password-protected PDF if you have a
**synthetic** one. Show the safe code and that other files in the batch
are unaffected.

## 5. Close

Uninstall is delete the project folder ([install.md](install.md)).
Downloads of masked files are not removed. Repeat: do not put the demo
files into git or into an AI chat.
