# Stage 0 handoff — Governance and threat model

## Stage and objective

Stage 0: set the constraints before any code exists. That means product scope,
non-goals, the entity and masking policy, a data-flow diagram, trust boundaries,
the threat model, privacy assumptions, the retention and cleanup policy, the
supported-PDF definition, the safe error-code taxonomy, the stage plan, and the
ignore rules. No application code.

**Status: complete and committed.** Cursor does not let the agent write
`.cursorignore`, so the agent wrote its content to `docs/cursorignore.template`
and the tech lead moved it into place. It was re-verified in revisions 1 and 2.

## Revision 2 (tech-lead answers, 10:25)

- **Q-01 resolved:**
  - DOCX CVs are redacted directly and returned as `redacted-<uuid>.docx` (D-15). There is
    no conversion between formats, and no Word or LibreOffice automation.
  - New Stages 6b, 10b and 11b cover DOCX validation and extraction, redaction, and
    verification. Their prompts were drafted by the agent and approved in principle (D-16).
  - The Stage 2 domain model is format-neutral from the start (D-17).
- DOCX rules were added:
  - Accepted and rejected Word formats.
  - Archive and XML safety limits.
  - What is always stripped.
  - Hidden-content categories and what happens when HR approves.
  - Error codes `DOCX_*`, `DOCX_MACRO_OR_TEMPLATE` and `VERIFY_STRUCTURE_MISMATCH`.
  - Threats T-23 to T-26.
  - A residual risk: rendering in Word is not verified.
- **D-18:** every stage ends with a git commit. This is now step 10 of the AGENTS.md workflow.
- Files changed in revision 2: `AGENTS.md`, `README.md`, `SECURITY.md`, `THREAT_MODEL.md`,
  `docs/product-scope.md`, `docs/masking-policy.md`, `docs/supported-pdf.md`,
  `docs/error-codes.md`, `docs/data-retention.md`, `docs/stage-plan.md`, this file.

## Revision 1 (tech-lead answers, 10:18)

- **Q-03 resolved (D-14):** the missing detectors are added to Stage 7
  (pattern and labeled-field entities) and Stage 8 (family sections, and unlabeled
  addresses in the contact block).
- **Q-04 resolved (D-13):** no image removal and no OCR. Candidate photos and text inside
  images are **not masked**. This is an accepted residual risk, disclosed in the README
  and threat model (T-07a), and to be disclosed in the UI and reports.
  `VERIFY_RESIDUAL_IMAGE` was removed from the error codes.
- **Q-08 resolved (D-08 revised):** the PoC is macOS only. Windows is a future, unscheduled
  stage; its Windows notes were removed from Stages 1, 3 and 15.
- Files changed in revision 1: `AGENTS.md`, `README.md`, `THREAT_MODEL.md`,
  `docs/product-scope.md`, `docs/masking-policy.md`, `docs/supported-pdf.md`,
  `docs/error-codes.md`, `docs/data-retention.md`, `docs/stage-plan.md`, this file.

## Architecture decisions

These are policy decisions; there is no code yet. The full log is in
`docs/product-scope.md` §5.

- D-01 to D-12 recorded, covering:
  - Loopback only.
  - The mandatory entity list. Salary is optional, per batch, and masked by default.
  - Vietnamese as the primary language, with English.
  - No image CVs.
  - Hidden-content review with approve/deny.
  - Retention of 24 hours at most.
  - Output files named `redacted-<uuid>.pdf`.
  - macOS only (Windows in a later stage).
  - Limits of 20 MB, 30 pages and 100 files.
  - Masked is not the same as anonymized.
  - No long-term audit trail.
  - Fail closed.
- Document state machine proposed in `docs/error-codes.md` §2. It adds `REJECTED` for
  when HR denies a document. Only verifier `PASSED` can lead to `COMPLETED`.
- `REVIEW_REQUIRED` comes in two kinds:
  - **Approvable:** hidden content, and low-confidence findings.
  - **Not approvable:** encrypted, too many pages, image-only pages, unreliable text.
    HR can only delete these.
- Hidden-content alerts show only the kind of content, its count and its page numbers,
  never the content itself. This keeps to the Stage 13 rule "never render extracted CV text".
- Embedded images pass through unchanged (D-13).
- PDF and DOCX share a format-neutral text model and the same detectors; redaction and
  verification happen in each file's own format (D-15 to D-17).
- The runtime storage root is outside the repository, under `~/Library/…/CVMasking`.
- Original filenames count as PII. They live only in the browser tab's memory.
- The ignore rules deny by default. The only exception is files named `synthetic-*` under
  a `tests/fixtures/synthetic/` directory.

## Files added/changed

| File | Change |
|---|---|
| `.gitignore` | Added |
| `.cursorignore` | Added by the tech lead from the agent-written template (agent write blocked); template removed |
| `AGENTS.md` | Changed: mission (macOS, languages, masked not anonymized); added governing-docs list, developer-environment rules, platform line |
| `README.md` | Written (was empty) |
| `SECURITY.md` | Written (was empty) |
| `THREAT_MODEL.md` | Added |
| `docs/product-scope.md` | Added |
| `docs/masking-policy.md` | Added |
| `docs/supported-pdf.md` | Added |
| `docs/data-retention.md` | Added |
| `docs/error-codes.md` | Added |
| `docs/stage-plan.md` | Added (stage prompts verbatim, plus Stage 0 notes) |
| `docs/stage-handoffs/stage-0.md` | Added (this file) |

## Commands run and exact results

1. `git init` gave `Initialized empty Git repository in /Users/nghiatran/projects/cv-masking/.git/`
   (git 2.54.0, Apple Git-157).
2. Ignore-rule verification using `git check-ignore --no-index --stdin`, run against a list of
   made-up paths (31 that must be ignored, 7 that must be tracked). The `.cursorignore` template
   was checked the same way, copied into a throwaway git repository as its `.gitignore`.
   - First run: two expectation mismatches.
     - `backend/tests/fixtures/synthetic/output/synthetic-a.pdf` was tracked. This is correct
       under the rule (a `synthetic-*` file inside the synthetic tree), so the test list was
       corrected.
     - `.DS_Store` was missing from the template, so OS junk patterns were added.
   - Final run:
     ```
     == .gitignore ==
     must-ignore: ALL 31 ignored
     must-track: none of 7 ignored (exit 1)
     == .cursorignore template ==
     must-ignore: ALL 31 ignored
     must-track: none of 7 ignored (exit 1)
     ```
3. Checks for code and documents, using `find` over the repository excluding `.git`:
   - Application code or manifests (`*.py`, `*.ts(x)`, `*.js(x)`, `*.sh`, `*.ps1`,
     `pyproject.toml`, `package.json`, `Makefile`, lockfiles): **0**
   - Documents, images or data (`pdf`, `doc*`, `png`, `jp*g`, `csv`, `sqlite*`, `db`, `log`,
     `zip`): **0**
4. PII-shape scan with `rg`:
   - Email-shaped strings: only `local@domain.tld`, the pattern template in masking-policy.md.
   - Runs of 9 or more digits: none (exit 1).
   - Vietnamese phone shapes containing real digits: none (exit 1).
   - URLs: only `http://127.0.0.1`.
5. `git status --short --untracked-files=all` shows the 12 files above as untracked.
   **No commit made.**
6. Revision 1 re-run: I tested the installed `.cursorignore` (copied into a throwaway repo
   as its `.gitignore`) and `.gitignore` again.
   ```
   == .gitignore ==
   must-ignore: ALL 31 ignored
   must-track: none of 7 ignored (exit 1)
   == .cursorignore (installed) ==
   must-ignore: ALL 31 ignored
   must-track: none of 7 ignored (exit 1)
   ```
   - Code or document files: 0.
   - Runs of 9 or more digits: none (exit 1).
   - Email-shaped strings: only `local@domain.tld`.
   - `git status` shows 13 untracked files, including `.cursorignore`. No commit made.
7. Revision 2 final checks, all identical to revision 1:
   - Both ignore files: all 31 must-ignore paths ignored, none of the 7 must-track paths ignored.
   - Code or document files: 0.
   - Runs of 9 or more digits: none.
   - Vietnamese phone shapes containing real digits: none.
   - Email-shaped strings: only `local@domain.tld`.
   - URLs: only `http://127.0.0.1`.
   - `git add -A` staged 13 files, all documentation or ignore rules.
   - Committed on `main` with the suggested message below.

There is no format, lint, type-check or test tooling yet, because Stage 1 creates it. Mermaid
diagrams were not validated by a renderer: that would need a new dependency such as
mermaid-cli via npx, which is outside Stage 0's scope. Check them in Markdown preview (manual step 3).

## Tests added

None. There is no code in this stage. The ignore-rule path matrix above serves as the
acceptance test. Its path lists are in `/tmp` and were not committed. Stage 1 can turn it
into a repeatable check if you approve.

## Security/privacy review

- Only synthetic content:
  - People: Nguyễn Văn Mẫu, Trần Thị Thử, Jane Example, John Sample.
  - Domains: `example.invalid` and `example.test`.
  - Identifier shapes are written with `X` placeholders; no real-looking numbers.
- No code, dependencies, subprocesses (other than `git`), or network calls were added.
- No real data was read. The only files read were `AGENTS.md` and the two empty files.
- Risks written down for the presentation (THREAT_MODEL.md §6 and data-retention.md §2):
  - Local processing does not stop browser copies, swap, backups or DLP agents, or
    browser extensions.
  - Cursor sends everything it's given off-machine.
  - Masked is not anonymized.
- Licensing: PyMuPDF (planned for Stage 6) is AGPL-3.0 or commercial. Flagged in SECURITY.md §4.
- Presidio (planned for Stage 7): its default NLP engine downloads spaCy models. This is
  flagged in the stage plan; it must be used with custom recognizers only, unless you
  approve otherwise.

## Known limitations

- Candidate photos and text inside images are not masked (D-13, accepted).
- The `.gitignore` re-allows a whole `tests/fixtures/synthetic/` tree for files named
  `synthetic-*`. A real CV renamed to match would be committable; human review is the control.
  Stage 1 could add a pre-commit check, subject to your approval.
- `*.png` and other image types are ignored everywhere. Frontend image assets will need
  explicitly reviewed exceptions in Stage 1 or 13.
- Detection-cue lists (masking-policy.md §3) are starting points, not complete lists of
  Vietnamese CV labels.
- Confidence thresholds (0.85 and 0.50) are placeholders until Stage 16 calibrates them.
- Whether the OS indexes or backs up the storage root (Spotlight, Time Machine) is
  still unverified; this belongs to Stage 3.

## Manual verification steps

1. `.cursorignore` is in place (done by the tech lead). In Cursor, confirm that a file matching
   one of its patterns doesn't appear in codebase search.
2. Read `docs/product-scope.md` §5 (decision log) and §6 (gaps) and confirm they match your
   intent, especially D-02, D-05, D-06 and D-09.
3. Open `THREAT_MODEL.md` and `docs/error-codes.md` in Markdown preview and check that the
   Mermaid diagrams render.
4. Run `git status --short --untracked-files=all` and confirm only the listed files appear.
5. Run `git check-ignore -v some/path/cv.pdf` and confirm it's ignored by `.gitignore`.

## Questions/decisions for the tech lead

| ID | Question | Current interim default |
|---|---|---|
| Q-01 | DOCX input. | **Resolved:** direct DOCX redaction, output `redacted-<uuid>.docx`, Stages 6b/10b/11b (D-15 to D-17) |
| Q-02 | **Approving hidden content.** When HR approves a CV with hidden content, is removing that content from the output correct? The alternative is keeping it, which the verifier can't vouch for. Also, should "display what it is" show only the kind, count and page, or the actual hidden text? Showing the text would conflict with the Stage 13 rule "never render extracted CV text". | Remove on approve; show kind, count and page only |
| Q-03 | Entities without a detector. | **Resolved:** added to Stages 7 and 8 (D-14) |
| Q-04 | Photos. | **Resolved:** not masked, no image removal or OCR (D-13) |
| Q-05 | **Audit trail.** Does the bank need a longer-lived record (IDs, times, codes, policy version only) beyond 24 hours? | None; purged with the batch |
| Q-06 | **Total batch size cap.** | 500 MB |
| Q-07 | **Quitting the app.** Should quitting erase all inputs, outputs and metadata immediately, rather than waiting for the 24-hour window? | Keep until the 24-hour window |
| Q-08 | Windows. | **Resolved:** its own future stage; PoC is macOS only (D-08) |
| Q-09 | **Hometown and place of birth.** I included these under `POSTAL_ADDRESS` as mandatory, interpreting your "address" approval. Confirm. | Mandatory |
| Q-10 | **Filename mapping.** Once the browser tab closes, HR loses which `redacted-<uuid>.pdf` belongs to which candidate. Is that acceptable, or should the UI offer a client-side mapping download (which would be a PII file the user saves)? | No mapping download |

## Suggested commit message

```
docs: stage 0 governance, threat model, and masking policy

Add scope, non-goals, decision log, masking policy (VI/EN), supported PDF
and DOCX input definition, retention/cleanup policy, safe error-code taxonomy
and state machine, threat model with data-flow diagram, stage plan (0-16 plus
DOCX stages 6b/10b/11b and a future Windows stage), and deny-by-default
ignore rules for git and Cursor. No application code.
```
