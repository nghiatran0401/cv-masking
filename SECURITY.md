# Security policy

This project processes real candidate CVs on bank-managed laptops. Its security
depends on both code controls and developer behavior. Read this file together
with [AGENTS.md](AGENTS.md) and [THREAT_MODEL.md](THREAT_MODEL.md).

## 1. Non-negotiable runtime rules

- The server binds to `127.0.0.1` only. `0.0.0.0`, `::`, LAN IPs, and hostnames are refused at startup.
- No outbound network calls from the server except one case: after HR clicks
  **Tải các liên kết**, the server GETs `https://data.ehiring.ehr.vib` only (D-50).
  No AWS or cloud storage, telemetry, analytics, crash reporting, update checks,
  remote fonts/CDNs, or external AI/LLM/API calls. The pasted URL is sent to the
  local API for that request and is not stored. Redirects to any other host are
  refused. The browser login cookie is not sent. TLS verification stays on and
  also trusts public certificates already installed in the Mac keychains.
- Inputs are never overwritten. Stored outputs are always new files named `redacted-<uuid>.pdf`
  or `redacted-<uuid>.docx`, matching the input format. The UI saves single-file downloads as
  `masked_<original filename>` from browser memory only. The bulk ZIP may also include the
  original File still in this tab, grouped under `output/candidate <name>/`; those originals
  must not be shared.
- PDF redaction uses PDF redaction annotations that are applied. Drawing boxes over text is not redaction.
- DOCX redaction removes the text from the XML. Highlighting, shading, font color, or hidden
  text is not redaction.
- DOCX archives and XML are untrusted: bounded in-memory reads, no extraction to disk, no
  DTDs, entity resolution, or network access in the XML parser.
- A document is `COMPLETED` only after independent verification `PASSED`.
- The UI never renders extracted CV text. Original filenames stay in the browser tab
  only (sessionStorage holds the language choice, not names).
- Raw PII (entity values, extracted text, original filenames) is never written to SQLite,
  logs, API status responses, CSV reports, snapshots, or test output.
- Errors cross boundaries only as codes from [docs/error-codes.md](docs/error-codes.md).
- The API accepts only loopback `Host` values, loopback `Origin` values, a startup
  session cookie, and a CSRF header. Requests without them fail closed.
- The desktop launcher is an unsigned `.command` file plus a local uv virtualenv
  (D-39). PyMuPDF remains AGPL-3.0 or commercial; bank legal must confirm before
  any distribution beyond this PoC. The one-time bootstrap token is passed in the
  first loopback URL and is not logged.
- When uncertain, fail closed: `REVIEW_REQUIRED` or `FAILED`.

## 2. Developer environment (Cursor and AI assistants)

Cursor sends prompts, attached files, and files the agent reads to remote model
providers for inference. "The app is local" does not make the development
environment local.

- **Never** open, paste, attach, drag in, screenshot, or describe a real CV (or any part
  of it) in Cursor or any AI tool. This includes filenames and "just one line" excerpts.
- **Never** place real CVs anywhere in the repository yourself, even temporarily. The only
  place real CVs may exist in the checkout is `data/`, written by the app itself (D-22).
- **Never** open, search, list, or attach anything under `data/` in Cursor, and never ask an
  agent to. It is in `.cursorignore`, but that is best-effort: a terminal command can still
  read it (see [docs/data-retention.md](docs/data-retention.md) §3).
- Exclude `data/` from Time Machine once: `tmutil addexclusion <project>/data`.
- Enable Cursor **Privacy Mode**. It limits retention by providers but does not stop data
  from being transmitted; it is not a substitute for the rule above.
- `.cursorignore` blocks indexing and agent reads of document, data, and log paths. It is a
  best-effort guard, not a security boundary.
- Debugging a real-document problem: reproduce it with a **synthetic** fixture that has the
  same structure. If you cannot, report only the error code, document UUID, page count,
  and structural facts (e.g. "two-column, table on page 2") — never content.
- **Never** set `CV_MASKING_AUTHORIZED_EVAL=1` or pass `--authorized` from Cursor or any
  agent. That path is for a human on the HR laptop only. From a normal Terminal (Cursor
  closed), with CVs **outside** this repo:

  ```bash
  export CV_MASKING_AUTHORIZED_EVAL=1
  cd backend
  uv run --locked python -m cv_masking.evaluation --authorized /absolute/path/to/cvs
  ```

  The printout is counts only (no filenames or values). Delete the CV copy afterwards.

## 3. Test data

- Only explicitly synthetic data. Synthetic people, companies, and email domains are listed
  in [docs/masking-policy.md](docs/masking-policy.md) §3. Email domains must be
  `example.invalid` or `example.test`.
- Identifier-shaped values (phone, CCCD/CMND, passport) in fixtures are generated from
  reserved or clearly invalid patterns defined in the test helpers, not typed from memory.
- Committed fixture files must be named `synthetic-*` and live under a
  `tests/fixtures/synthetic/` directory; every other document type is git-ignored.
  Prefer generating fixtures at test time.
- `scripts/check-repo-files.sh` enforces this on the content in the git index. It runs
  as a pre-commit hook (installed by `make install`) and on every tracked file in
  `make check`. It refuses:
  - document, image, archive, database, spreadsheet, mail, and log extensions;
  - files whose first bytes identify them as PDF, ZIP/DOCX, OLE/DOC, RTF, SQLite, PNG,
    JPEG, GIF, gzip, 7z, or RAR, whatever their name;
  - any file over 1 MiB, including synthetic fixtures.

  It never prints file paths, since a CV's file name often contains the candidate's name.
  `git commit --no-verify` skips the hook but not `make check`. The guard is a safety
  net, not a boundary: plain-text personal data in an ordinary source file is not
  detected.
- Test names, parametrize ids, snapshots, and assertion messages must not contain entity
  values; use entity type and case index instead.

## 4. Dependencies and subprocesses

- Each new dependency or subprocess needs a written justification in the commit message
  (purpose, license, network behavior, native code, packaging impact).
- Lockfiles are committed; versions are pinned.
- npm never runs dependency install scripts (`ignore-scripts=true` in `frontend/.npmrc`),
  and `frontend/package.json` must not define lifecycle or `pre`/`post` hook scripts.
  Both rules are tested.
- Dependencies that phone home (telemetry, update checks, model downloads at runtime) are
  forbidden unless the behavior is fully disabled in code and tested.
- Licensing note: PyMuPDF is AGPL-3.0 or commercial. Bank legal must
  confirm the license path before any distribution beyond the PoC.

## 5. Reporting a problem

This is an internal PoC with no public disclosure channel. Report suspected
leakage or vulnerabilities directly to the tech lead. In the report include only
error codes, document UUIDs, and steps to reproduce with synthetic data.
**Do not attach the affected CV or its output.**

If real candidate data is found in the repository, logs, a commit, or an AI chat:
1. Stop work and notify the tech lead.
2. Do not push. If already pushed, the history must be rewritten and the remote purged.
3. Record what was exposed (by category, not content) and where.

## 6. Known limitations

See [THREAT_MODEL.md](THREAT_MODEL.md) §6. The most important: **masked output is
not anonymous**, and "local" does not protect against malware on the laptop,
browser extensions, backups, or data given to AI tools.
