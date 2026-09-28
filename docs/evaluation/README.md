# Evaluation harness (Stage 16)

The harness measures detection and redaction on **synthetic** annotated CVs
that are generated in memory at run time. PDF and DOCX bytes are never
committed (file guard: 1 MiB, no tracked documents). Values follow
[masking-policy.md](../masking-policy.md) §3 and never appear in the report.

```bash
make eval
# equivalent: cd backend && uv run --locked python -m cv_masking.evaluation
# Markdown: python -m cv_masking.evaluation --markdown
```

The report is metadata only: counts, precision, recall, false negatives,
leakage of distinctive gold values (≥6 characters), review-required rate,
failure rate, and duration. Formats are listed separately. Photos and
embedded images are recorded as **unmasked** (D-13).

The synthetic set is two files per format: one labeled CV (plus a 16×16
image on the PDF) and one malformed file so failures stay visible.

Scoring is exact `(entity type, part, start, end)` against gold spans found
in extracted text. A gold span nested inside a longer annotated value is
dropped so a nationality line is not also counted as gender. Distinctive
gold values remaining in redacted bytes increment `leaked_distinctive`.
Short values (under 6 characters) are excluded from the leak scan, matching
verification (D-37).

The harness is a composition root: it wires extractors, `DetectionService`,
and redactors in process. It does **not** start FastAPI, SQLite, or write
under `data/`.

## Authorized local run (optional, D-40)

**Never** run this path from Cursor, an agent, or any AI tool. **Never**
place real CVs in the repository. If bank HR later authorizes a local
measurement on real files, a human does it on the HR laptop only.

Procedure (human, HR laptop, no AI):

1. Copy authorized CVs into a directory **outside** the git checkout (not
   `data/`, not this repository).
2. Confirm Cursor is closed and no agent will read that directory.
3. From a normal Terminal (not Cursor chat):

   ```bash
   export CV_MASKING_AUTHORIZED_EVAL=1
   cd backend
   uv run --locked python -m cv_masking.evaluation --authorized /absolute/path/to/that/directory
   ```

4. Share **only** the printed JSON or Markdown. It contains no filenames,
   paths, or values. Precision/recall are omitted on this path (no gold
   labels). Operational counts only: documents seen, failed,
   review-required, distinctive-leak count, duration.
5. Delete the copy of the CVs when finished. Do not commit the report into
   git if you pasted extra notes that name people or files.

Without `CV_MASKING_AUTHORIZED_EVAL=1` the command raises `PermissionError`.
Symlinks, empty files, and files over 21 MiB are skipped. Unrecognized
magic is skipped. Agents must not set this variable against real files.
