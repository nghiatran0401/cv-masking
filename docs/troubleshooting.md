# Troubleshooting

Safe messages only. Do not copy CV text, filenames that contain names, or
`data/` paths into Cursor or tickets. Use the document UUID and the error
code from [error-codes.md](error-codes.md).

## Launcher and browser

| Symptom | What to try |
|---|---|
| Gatekeeper blocks `.command` | Finder → right-click `scripts/cv-masking.command` → Open. The launcher is unsigned (D-39). |
| Browser does not open / 403 on session | Quit `make dev` if it is using port 8765, then launch again so a fresh bootstrap token is issued. |
| `SECURITY_TOKEN_INVALID` | Reload from the launcher (or `/?bootstrap=…` once). Dev (`make dev`) does not use the token. |
| `SECURITY_RATE_LIMITED` | Wait a minute (240 requests / 60 s). A stuck auto-refresh shares the budget. |
| Port already in use | Another instance holds `data/lock/instance.lock`, or `make dev` is running. Quit that process. |
| Intel Mac | Not tested. Install on that machine with `make install` and `make build`; do not copy `backend/.venv` from Apple Silicon. |
| UI missing / not Vietnamese | Run `make build` on this tree so `cv_masking/static` exists, then relaunch. |

## Upload and types

| Code | Meaning | Operator action |
|---|---|---|
| `UPLOAD_UNSUPPORTED_TYPE` | Not PDF or DOCX | Export to text PDF or DOCX. No `.doc`, images, or scans. |
| `UPLOAD_SPOOFED_TYPE` | Name and bytes disagree | Re-save the file from Word/Preview. |
| `DOCX_MACRO_OR_TEMPLATE` | `.docm` / template | Save as `.docx` without macros. |
| `UPLOAD_FILE_TOO_LARGE` | Over 20 MB | Reduce size; do not zip-inside-zip. |
| `UPLOAD_BATCH_FILE_LIMIT` | 50 files | Start another batch (D-30). |
| `UPLOAD_DUPLICATE` | Same hash in this batch | Skip; already queued. |
| `UPLOAD_BATCH_CLOSED` | Batch already started | New batch. |

## Validation (delete-only reviews)

Encrypted, image-only, too many pages, or no text: the document cannot be
masked in this PoC. Deny/delete. Scanned CVs are out of scope (no OCR).

Malformed PDF/DOCX (`PDF_MALFORMED`, `DOCX_MALFORMED`, unsafe archive,
resource limits) fail closed. Re-export the file; retrying the same bytes
fails the same way (`T` codes).

## Processing and review

| Code | Meaning | Operator action |
|---|---|---|
| `DETECT_NO_CANDIDATE_NAME` | Name may be unmasked | Read the masked file; keep or delete. |
| `DETECT_LOW_CONFIDENCE` / `MAP_AMBIGUOUS` | Uncertain finding | Same: inspect masked output. |
| `MAP_FAILED` / `DETECT_FAILED` | Deterministic failure | Do not retry the same file; redact by hand. |
| `VERIFY_RESIDUAL_*` | Leak or leftover metadata | Treat as failed redaction; do not share. |
| `JOB_TIMEOUT` | Over 120 s | File too heavy or pathological; split or skip. |
| `JOB_INTERRUPTED` | App stopped mid-document | Re-upload. |
| `STORAGE_WRITE_FAILED` | Disk/permissions | Free space; check `data/` is owner-only. |

Downloads are `redacted-<uuid>.…`. If Word or Preview still shows a
contact value in **body text**, do not share the file. If it appears only
inside a **photo**, that is the accepted D-13 limitation.

## After a crash

Restart the `.command`. Documents left `VALIDATING` / `PROCESSING` /
`VERIFYING` become `JOB_INTERRUPTED`. Work leftovers under `data/work/`
are swept after 1 h. Do not ask an agent to inspect `data/`.

## Developer (synthetic only)

`make check` is the quality gate. `make eval` is synthetic metrics only.
If evaluation or tests fail, reproduce with generated fixtures — never
with a real CV.
