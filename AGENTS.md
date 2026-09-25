# AGENTS.md

## Mission
Build a localhost-only web application for bank-managed macOS laptops (Windows is a later, separate stage) that batch-detects and permanently redacts approved PII/sensitive entities from CV PDF and DOCX files (Vietnamese primary, English supported), each redacted in its own format. No runtime document data may leave the laptop. Output is masked, not anonymized.

## Governing documents
Read before every stage; they override assumptions:
- [SECURITY.md](SECURITY.md) — runtime and developer-environment rules.
- [THREAT_MODEL.md](THREAT_MODEL.md) — assets, trust boundaries, threats, residual risks.
- [docs/product-scope.md](docs/product-scope.md) — scope, non-goals, decision log, known gaps.
- [docs/masking-policy.md](docs/masking-policy.md) — entity catalogue, mandatory vs optional, confidence, non-text components.
- [docs/supported-pdf.md](docs/supported-pdf.md) — accepted inputs, limits, hidden content.
- [docs/data-retention.md](docs/data-retention.md) — privacy assumptions, storage, retention, cleanup.
- [docs/error-codes.md](docs/error-codes.md) — safe error codes and document state machine.
- [docs/stage-plan.md](docs/stage-plan.md) — verbatim stage prompts and Stage 0 notes.

## Developer-environment rules (Cursor / AI)
- Everything the agent reads or is given is sent off-machine for inference. Treat the chat as a network boundary.
- Never read, list, search, or open the runtime `data/` folder in the repository root (docs/data-retention.md §3), or files outside the repository that may hold runtime data (Downloads, Desktop, Documents, mail attachments). Scope searches and shell commands so they cannot descend into `data/`.
- Never read, open, or request a file that is not synthetic. If a file of unknown origin appears (PDF, DOCX, image, CSV, SQLite, log), stop and ask; do not open it.
- If the user pastes what looks like real candidate data, do not process or repeat it; ask them to replace it with a synthetic reproduction.
- Synthetic values follow docs/masking-policy.md §3 and SECURITY.md §3.
- Protected files (e.g. `.cursorignore`) that the agent cannot write must be handed to the user, not worked around.

## Hard security rules
- Never add AWS, cloud storage, telemetry, analytics, remote fonts/CDNs, or external AI/API calls.
- Never inspect, copy, generate from, commit, or log real candidate data.
- Use only clearly synthetic fixtures.
- Never store raw PII values in SQLite, logs, API status responses, CSV reports, snapshots, or test output.
- Never bind the server to 0.0.0.0; use 127.0.0.1 only.
- Never overwrite an input document.
- Never mark a document COMPLETED unless independent verification passes.
- Never implement visual overlays as redaction; use PDF redaction APIs and apply them.
- Never implement DOCX redaction with formatting (highlight, shading, font color, hidden text); remove the text from the XML.
- Never convert between PDF and DOCX, and never automate Word or LibreOffice.
- Never weaken validation, cleanup, or tests to make a stage pass.
- Do not introduce a dependency or subprocess without explaining its security and packaging impact.
- Do not work beyond the requested stage.

## Architecture
- Localhost web app on macOS; runtime files in the project's git- and Cursor-ignored `data/` folder (D-22). Do not add Windows-specific code before the Windows stage.
- React/Vite/TypeScript frontend.
- Python 3.12/FastAPI backend.
- Core processing independent from FastAPI, SQLite, and local filesystem adapters.
- Dependency direction: API → application services → domain/ports; adapters implement ports.
- Format adapters (PDF, DOCX) produce one format-neutral text model; detectors depend only on that model.
- PII detector output includes type, location (PDF page + boxes, or DOCX part + character range), confidence, detector/version, replacement, and review flag.
- Raw entity text is transient only.

## Required workflow for every stage
1. Read AGENTS.md and relevant docs.
2. Inspect the current repository and tests.
3. Restate the requested stage, assumptions, files to change, risks, and acceptance criteria.
4. Wait for approval when the prompt explicitly requires a plan-only response.
5. Implement only the approved stage in small cohesive changes.
6. Add/update tests for success, failure, boundaries, and security behavior.
7. Run format, lint, type-check, unit, and relevant integration tests.
8. Review the diff for PII leakage, network calls, broad permissions, unsafe paths, and scope creep.
9. Create docs/stage-handoffs/stage-N.md.
10. Commit the stage with git once every check passes, using the handoff's suggested commit message. Before committing, confirm `git status` contains no ignored-type or runtime files. Never commit a failing stage; never push unless asked.
11. Stop and report; do not start the next stage.

## Handoff format
- Stage and objective
- Architecture decisions
- Files added/changed
- Commands run and exact results
- Tests added
- Security/privacy review
- Known limitations
- Manual verification steps
- Questions/decisions for the tech lead
- Suggested commit message

## Completion rules
A stage is incomplete if tests are skipped, commands fail, sensitive values enter logs/storage, documentation is missing, or behavior cannot be demonstrated locally.