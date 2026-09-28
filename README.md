# CV Masking (local PoC)

A localhost-only tool for bank HR staff that batch-detects and permanently
redacts personal and sensitive information from CVs (PDF and Word DOCX) on
their own macOS laptop. CVs are never sent to any network service. Windows
is not supported yet.

HR: double-click `scripts/cv-masking.command` — see
[docs/install.md](docs/install.md) and
[docs/operator-guide.md](docs/operator-guide.md).

## Development (macOS)

Requirements: [uv](https://docs.astral.sh/uv/) ≥ 0.10.6 (it provides Python 3.12),
Node.js ≥ 24 with npm, and GNU Make.

```bash
uv python install 3.12   # one-time
make install             # locked dependencies, Playwright Chromium, pre-commit file guard
make build               # production UI into the Python package
make dev                 # backend 127.0.0.1:8765, frontend 127.0.0.1:5173
make check               # file guard + lint + type-check + UI build + tests
make eval                # synthetic metadata-only metrics (no real CVs)
```

Open <http://127.0.0.1:5173> for development. The `.command` launcher serves
the UI from <http://127.0.0.1:8765> and does not start Node.

Both servers bind to `127.0.0.1` only. Set `CV_MASKING_PORT` to change the
backend port (the Vite proxy expects 8765).

## What it does

- Accepts batches of text-based PDF and DOCX CVs (Vietnamese and English).
- Detects mandatory entities (name, contacts, IDs, address, date of birth, sensitive
  attributes, references) and optionally salary.
- Redacts each file in its own format, writes `redacted-<uuid>.pdf` or
  `.docx`, and releases it only after independent verification passes.
- Holds uncertain documents for HR review.

## What it does not do

- **It does not anonymize.** Employers, schools, titles, and dates remain.
- It does not mask photos or text inside images.
- It does not process scanned CVs, legacy `.doc`, or macro-enabled Word files,
  and it never converts between PDF and Word.
- It does not protect against malware, browser extensions, backups, or
  anything pasted into AI tools such as Cursor.

## Documentation

| Document | Contents |
|---|---|
| [docs/install.md](docs/install.md) | Install, run, uninstall |
| [docs/operator-guide.md](docs/operator-guide.md) | How HR uses the app |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Launcher issues and error codes |
| [docs/masking-policy.md](docs/masking-policy.md) | What is masked |
| [docs/error-codes.md](docs/error-codes.md) | Safe codes and document states |
| [docs/supported-pdf.md](docs/supported-pdf.md) | Accepted PDF and DOCX inputs |
| [docs/data-retention.md](docs/data-retention.md) | Storage and cleanup |
| [SECURITY.md](SECURITY.md) | Runtime and developer security rules |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Trust boundaries and residual risks |
| [docs/product-scope.md](docs/product-scope.md) | Scope, non-goals, decision log |
| [AGENTS.md](AGENTS.md) | Rules for implementation agents |
