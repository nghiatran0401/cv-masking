# CV Masking (local PoC)

A localhost-only tool for bank HR staff that batch-detects and permanently
redacts personal and sensitive information from CVs (PDF and Word DOCX) on their own macOS
laptop (Windows support is a later stage). CVs are never sent to any network service.

> **Status:** Stage 16 — evaluation harness and release-candidate docs.
> Synthetic metadata-only metrics: `make eval`. HR launch:
> [docs/install.md](docs/install.md), [docs/operator-guide.md](docs/operator-guide.md).
> See [docs/stage-plan.md](docs/stage-plan.md).

## Development (macOS)

Requirements: [uv](https://docs.astral.sh/uv/) ≥ 0.10.6 (it provides Python 3.12),
Node.js ≥ 24 with npm, and GNU Make.

```bash
uv python install 3.12   # one-time
make install             # locked dependencies, Playwright Chromium, pre-commit file guard
make build               # production UI into the Python package
make dev                 # backend 127.0.0.1:8765, frontend 127.0.0.1:5173
make check               # file guard + lint + type-check + UI build + tests (quality gate)
make eval                # synthetic metadata-only precision/recall report (no real CVs)
```

Open <http://127.0.0.1:5173> for development. HR double-clicks
`scripts/cv-masking.command` (see [docs/install.md](docs/install.md)); that
serves the UI from <http://127.0.0.1:8765> and does not start Node.

Both servers bind to `127.0.0.1` only; the backend host cannot be changed. Set
`CV_MASKING_PORT` to change the backend port (the Vite proxy expects 8765).

## What it does (target)

- Accepts batches of text-based PDF and DOCX CVs (Vietnamese and English).
- Detects mandatory entities (name, contacts, IDs, address, date of birth, sensitive
  attributes, references) and optionally salary.
- Redacts each file in its own format (true PDF redaction, or text removal inside the DOCX),
  writes `redacted-<uuid>.pdf` or `redacted-<uuid>.docx`, and releases it only after
  independent verification passes.
- Holds documents with hidden content or uncertain findings for HR review.

## What it does not do

- **It does not anonymize.** Employers, schools, titles, and dates remain and can
  identify a candidate. Treat outputs as personal data.
- It does not mask photos or text inside images; embedded images pass through unchanged.
- It does not process scanned/image CVs, legacy `.doc`, or macro-enabled Word files, and it
  never converts between PDF and Word.
- It does not protect against malware on the laptop, browser extensions, backups, or
  anything pasted into AI tools such as Cursor.

## Documentation

| Document | Contents |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules for implementation agents |
| [SECURITY.md](SECURITY.md) | Runtime and developer security rules |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Data flow, trust boundaries, threats, residual risks |
| [docs/product-scope.md](docs/product-scope.md) | Scope, non-goals, decision log, known gaps |
| [docs/masking-policy.md](docs/masking-policy.md) | Entities, labels, confidence, non-text components |
| [docs/supported-pdf.md](docs/supported-pdf.md) | Accepted PDF and DOCX inputs, limits, hidden content |
| [docs/data-retention.md](docs/data-retention.md) | Privacy assumptions, retention, cleanup |
| [docs/error-codes.md](docs/error-codes.md) | Safe error codes and document states |
| [docs/stage-plan.md](docs/stage-plan.md) | Implementation stages |
| [docs/install.md](docs/install.md) | macOS install, run, uninstall (Stage 15) |
| [docs/operator-guide.md](docs/operator-guide.md) | HR operating instructions |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Safe codes and launcher issues |
| [docs/adr.md](docs/adr.md) | Architecture decision records |
| [docs/demo-script.md](docs/demo-script.md) | Synthetic demo walkthrough |
| [docs/release-checklist.md](docs/release-checklist.md) | Go/no-go checklist |
| [docs/evaluation/](docs/evaluation/) | Synthetic eval; authorized-run procedure (D-40) |
| [docs/stage-handoffs/](docs/stage-handoffs/) | Per-stage handoff reports |
