# CV Masking (local PoC)

This tool helps bank HR staff hide personal information in CVs. It runs only
on the HR person's own Mac. CV files stay on that laptop. The app does not
send them to any internet service. Windows is not supported yet.

HR staff open the app by double-clicking `scripts/cv-masking.command`. See
[docs/install.md](docs/install.md) and
[docs/operator-guide.md](docs/operator-guide.md).

## How it works

**1. HR opens the app**
The browser talks only to this laptop (`127.0.0.1`).
Tech: React and TypeScript for the screen. Python 3.12 and FastAPI for the server.

**2. HR uploads a batch**
Up to 50 text PDF or Word (`.docx`) files. Vietnamese and English are both
supported. Salary is hidden by default. HR can turn that off for the whole batch.
If HR has a list of CV links (often only reachable on the company
network), they paste the URLs in the app, open each link in this browser,
save the files into a folder, then choose the folder. The app never fetches
those URLs; the local server never sees the links.
Tech: the screen sends the files to the local server. SQLite stores job status
and counts only. It never stores the personal text itself.

**3. Each file is checked**
The app rejects the wrong file type, files that are too big, files with too
many pages, scanned PDFs, and Word files that contain macros. The original
file is never changed.
Tech: PyMuPDF for PDF. `defusedxml` for safe reading of Word XML.

**4. The text is taken out**
PDF and Word are turned into the same internal text, so the next step is the
same for both formats.
Tech: PyMuPDF for PDF. Word XML for `.docx`.

**5. Personal information is found**
The app looks for names, phone numbers, email, ID and passport numbers,
addresses, date of birth, gender, marital status, nationality, religion,
ethnicity, health, family details, and referee names. Salary is included
when the switch is on. Company names, schools, job titles, dates, and
personal URLs stay in the file.
Tech: Microsoft Presidio for pattern matching, plus our own Vietnamese and
English label and section rules. No cloud AI and no language model.

**6. That text is removed from the file**
In a PDF, the text is deleted and replaced with a label such as `[NAME]`.
In Word, the characters are deleted from the file and replaced with the same
kind of label. Hidden content (comments, metadata, and invisible text) is
always removed.
Tech: PyMuPDF redaction for PDF. Direct XML edits for Word. A PDF is never
turned into Word, and Word is never turned into a PDF.

**7. The output is checked again**
The app reads the new file and looks for personal information a second time.
If any is still there, HR cannot download that file as finished.
Tech: the same detectors, run again on their own.

**8. HR reviews uncertain files**
Clear files are ready. Uncertain files wait. HR views a masked PDF in the
app (Word is download-only) and either keeps it or deletes it.
Tech: one local background worker, one document at a time. The screen shows
status and counts, never the original personal text.

**9. HR downloads the result**
PDF can be viewed first. Word is download-only. One file, or all downloadable
files as `output.zip` (including rows still in review). Files that could not
strip hidden content are left out. Each candidate folder holds the original
file and `masked_` plus that name. Share only the `masked_` copies you have
checked. Original names stay in this browser tab; they are not stored on the
server.

**10. HR deletes the batch when they are done**
Files stay on the laptop until HR deletes the batch. Temporary work files are
removed after each job.

## Limits

- The output is masked. Company names, schools, job titles, dates, and
  personal URLs stay, so a reader may still recognise the person. This is
  not full anonymization.
- Photos, and any text inside images, stay in the file.
- The app accepts text-based PDF and `.docx` only. Scanned CVs, old `.doc`
  files, and Word files with macros are rejected.
- The app cannot protect the laptop from malware, browser extensions, or
  backups. Pasting a CV into an AI tool such as Cursor sends that text off
  the laptop.

## Development (macOS)

You need [uv](https://docs.astral.sh/uv/) 0.10.6 or newer (it installs Python
3.12), Node.js 24 or newer with npm, and GNU Make.

```bash
uv python install 3.12   # one-time
make install             # locked dependencies, Playwright Chromium, pre-commit file guard
make build               # production UI into the Python package
make dev                 # backend 127.0.0.1:8765, frontend 127.0.0.1:5173
make check               # file guard + lint + type-check + UI build + tests
make eval                # synthetic metadata-only metrics (no real CVs)
```

Open <http://127.0.0.1:5173> while developing. The `.command` launcher serves
the screen from <http://127.0.0.1:8765> and does not start Node.

Both servers listen on `127.0.0.1` only. Set `CV_MASKING_PORT` to change the
backend port (the Vite proxy expects 8765).

## Documentation

| Document | Contents |
|---|---|
| [docs/install.md](docs/install.md) | Install, run, uninstall |
| [docs/operator-guide.md](docs/operator-guide.md) | How HR uses the app |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Launcher problems and error codes |
| [docs/masking-policy.md](docs/masking-policy.md) | What is hidden |
| [docs/error-codes.md](docs/error-codes.md) | Error codes and document states |
| [docs/supported-pdf.md](docs/supported-pdf.md) | Which PDF and Word files are accepted |
| [docs/data-retention.md](docs/data-retention.md) | Where files are stored, and how cleanup works |
| [SECURITY.md](SECURITY.md) | Security rules for running and building the app |
| [THREAT_MODEL.md](THREAT_MODEL.md) | What the app protects, and what it does not |
| [docs/product-scope.md](docs/product-scope.md) | Scope, non-goals, decision log |
| [AGENTS.md](AGENTS.md) | Rules for implementation agents |
