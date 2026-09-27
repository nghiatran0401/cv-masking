# Safe error-code taxonomy and document states

Status: finalized in Stage 2. Implemented as the closed enums `ErrorCode` and
`ReviewReason` in `backend/src/cv_masking/domain/codes.py`; the tables below are
checked against the code by `backend/tests/domain/test_codes.py`. Mapped to HTTP
responses in Stages 5 and 14.

## 1. Rules for every error

1. **Codes are a closed enum.** No free-form error strings cross a boundary (API, UI,
   SQLite, logs, CSV).
2. **Messages are static constants** keyed by code, localized (vi/en) in the UI. They are
   never built from exception text, file contents, file names, or paths.
3. **Allowed parameters** in any error payload: document UUID, batch UUID, page numbers,
   counts, configured limits, and the code itself. Nothing else.
4. **Exceptions are not persisted.** Stack traces go to stderr only in developer mode, with
   exception messages from third-party parsers suppressed (they may echo document bytes). In
   production mode only the code and a random correlation id are logged.
5. **Unknown errors fail closed** as `INTERNAL_ERROR` → document `FAILED`. No catch-all may
   convert an error into success or silently skip a document.
6. **One document's error never changes another document's state.**

## 2. Document states (finalized in Stage 2)

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> UPLOADED: mark_uploaded (stored + hashed)
    CREATED --> FAILED: reject_upload (UPLOAD_*, STORAGE_*, INTERNAL_ERROR)
    UPLOADED --> VALIDATING: start_validation
    VALIDATING --> QUEUED: validation_passed
    VALIDATING --> REVIEW_REQUIRED: validation_needs_review (blocking or hidden content)
    VALIDATING --> FAILED: fail
    REVIEW_REQUIRED --> QUEUED: approve_review (hidden content only)
    QUEUED --> PROCESSING: start_processing (attempt + 1, policy recorded)
    PROCESSING --> VERIFYING: output_written
    PROCESSING --> FAILED: fail
    PROCESSING --> QUEUED: requeue_after_interruption (attempt < 3)
    VERIFYING --> QUEUED: requeue_after_interruption (attempt < 3)
    PROCESSING --> FAILED: requeue_after_interruption (attempt = 3, JOB_INTERRUPTED)
    VERIFYING --> FAILED: requeue_after_interruption (attempt = 3, JOB_INTERRUPTED)
    VERIFYING --> COMPLETED: record_verification PASSED, no findings reasons
    VERIFYING --> REVIEW_REQUIRED: record_verification PASSED with findings reasons, or REVIEW_REQUIRED
    VERIFYING --> FAILED: record_verification FAILED, or fail
    REVIEW_REQUIRED --> COMPLETED: approve_review (findings only, verification PASSED)
    REVIEW_REQUIRED --> REJECTED: deny_review
    note right of CREATED: cancel is allowed from every non-terminal state except REVIEW_REQUIRED
    COMPLETED --> [*]
    FAILED --> [*]
    REJECTED --> [*]
    CANCELLED --> [*]
```

Terminal states: `COMPLETED`, `FAILED`, `REJECTED`, `CANCELLED`. Only `COMPLETED`
documents have a downloadable output. `COMPLETED` is reachable **only** with a
verification `PASSED` result: either directly, or when HR approves findings-only
review reasons on an output that already passed. A verifier `REVIEW_REQUIRED`
result can never be approved into `COMPLETED`; HR can only deny it.

`cancel` moves any non-terminal state except `REVIEW_REQUIRED` (which uses
deny) to `CANCELLED`, carrying `JOB_CANCELLED`. A job may be processed at most
3 times (`MAX_PROCESSING_ATTEMPTS`).

### Review reasons

| Reason | Kind | HR can |
|---|---|---|
| `PDF_ENCRYPTED` | blocking | Delete only |
| `PDF_TOO_MANY_PAGES` | blocking | Delete only |
| `PDF_NO_TEXT_LAYER` | blocking | Delete only |
| `PDF_TEXT_UNRELIABLE` | blocking | Delete only |
| `DOCX_ENCRYPTED` | blocking | Delete only |
| `DOCX_TOO_LARGE_TEXT` | blocking | Delete only |
| `DOCX_NO_TEXT` | blocking | Delete only |
| `PDF_HIDDEN_CONTENT` | hidden_content | Approve (content removed, processing continues) or deny |
| `DOCX_HIDDEN_CONTENT` | hidden_content | Approve (content removed, processing continues) or deny |
| `DETECT_LOW_CONFIDENCE` | findings | Approve the verified output, or deny |
| `DETECT_NO_CANDIDATE_NAME` | findings | Check that the candidate's name is masked; approve the verified output, or deny |
| `MAP_AMBIGUOUS` | findings | Approve the verified output, or deny |
| `VERIFY_REVIEW` | verifier | Deny only |

A job is approvable only when **all** its reasons are hidden_content, or
**all** are findings (with verification PASSED). Any blocking or verifier reason
makes the job deny-only.

Batch states: `OPEN` (accepting uploads; salary toggle editable) → `RUNNING`
(toggle locked) → `FINISHED` (all documents terminal or `REVIEW_REQUIRED`).
`PURGED` is reachable from any state.

## 3. Codes

`R` = retryable: HR may re-upload the same file into the batch; `T` = re-uploading the
same file will fail the same way. A `—` code is not an error but a review reason.
Error codes put the document in `FAILED` (terminal); `—` rows put it in
`REVIEW_REQUIRED` (see the review-reason table in §2). Per retention decision D-06 the
input is deleted at a terminal state, so a retry is always a fresh upload.

### Upload (Stage 5)

| Code | R/T | Meaning |
|---|---|---|
| `UPLOAD_UNSUPPORTED_TYPE` | T | Not a PDF or DOCX (legacy `.doc`, image, other). |
| `UPLOAD_SPOOFED_TYPE` | T | Extension or content type disagrees with the file's content. |
| `DOCX_MACRO_OR_TEMPLATE` | T | Macro-enabled document or template (`.docm`, `.dotx`, `.dotm`). |
| `UPLOAD_FILE_TOO_LARGE` | T | Exceeds per-file size limit. |
| `UPLOAD_BATCH_FILE_LIMIT` | T | Batch already has the maximum number of files. |
| `UPLOAD_BATCH_SIZE_LIMIT` | T | Batch total size limit reached. |
| `UPLOAD_DUPLICATE` | T | Same content hash already in this batch. |
| `UPLOAD_MALFORMED_REQUEST` | R | Multipart request invalid or incomplete. |
| `UPLOAD_TIMEOUT` | R | Upload did not finish within the request timeout. |
| `UPLOAD_BATCH_CLOSED` | T | Batch is no longer accepting uploads. |

### PDF validation and extraction (Stage 6)

`PDF_HIDDEN_CONTENT` and `DOCX_HIDDEN_CONTENT` are the only approvable
validation reasons.

| Code | R/T | Meaning |
|---|---|---|
| `PDF_MALFORMED` | T | Cannot be parsed. |
| `PDF_NO_PAGES` | T | Zero pages. |
| `PDF_ENCRYPTED` | — | Password-protected or encrypted (blocking review). |
| `PDF_TOO_MANY_PAGES` | — | Exceeds page limit (blocking review). |
| `PDF_NO_TEXT_LAYER` | — | At least one page is image-only (blocking review). |
| `PDF_TEXT_UNRELIABLE` | — | Text cannot be reliably mapped to Unicode (blocking review). |
| `PDF_HIDDEN_CONTENT` | — | Hidden content found; awaiting HR approve/deny. |
| `PDF_RESOURCE_LIMIT` | T | Decompression or object-count limits exceeded. |

### DOCX validation and extraction (Stage 6b)

| Code | R/T | Meaning |
|---|---|---|
| `DOCX_MALFORMED` | T | Archive or XML cannot be parsed, or XML uses forbidden features (DTD, entities). |
| `DOCX_ENCRYPTED` | — | Password-protected (OLE compound container; blocking review). |
| `DOCX_UNSAFE_ARCHIVE` | T | Unsafe or duplicate entry names. |
| `DOCX_RESOURCE_LIMIT` | T | Entry count, uncompressed size, or compression ratio exceeded. |
| `DOCX_TOO_LARGE_TEXT` | — | Extracted text exceeds the length limit (blocking review). |
| `DOCX_NO_TEXT` | — | No extractable text (blocking review). |
| `DOCX_HIDDEN_CONTENT` | — | Hidden content found; awaiting HR approve/deny. |

### Detection and mapping (Stages 7–9)

| Code | R/T | Meaning |
|---|---|---|
| `DETECT_LOW_CONFIDENCE` | — | One or more findings require review. |
| `DETECT_NO_CANDIDATE_NAME` | — | No candidate name was detected; the name may be unmasked, review required. |
| `DETECT_FAILED` | R | A detector raised an error. |
| `MAP_AMBIGUOUS` | — | A finding's word overlaps another word drawn on top of it; all candidate boxes are redacted, review required. |
| `MAP_FAILED` | R | Mapping raised an error, or a visible character of a finding has no source word box. |

### Redaction (Stages 10, 10b)

| Code | R/T | Meaning |
|---|---|---|
| `REDACT_FAILED` | R | Redaction could not be applied. |
| `REDACT_SANITIZE_FAILED` | R | Metadata/hidden-content removal failed. |
| `REDACT_OUTPUT_WRITE_FAILED` | R | Output could not be written atomically. |

### Verification (Stages 11, 11b)

Codes are shared by PDF and DOCX; the job's format says which verifier ran.
A failed verification keeps every code it found; the job shows the most serious one,
in this order (`VERIFY_FAILURE_PRECEDENCE`): `VERIFY_RESIDUAL_FINDING`,
`VERIFY_RESIDUAL_DETECTION`, `VERIFY_RESIDUAL_METADATA`, `VERIFY_OUTPUT_INVALID`,
`VERIFY_PAGE_COUNT_MISMATCH`, `VERIFY_STRUCTURE_MISMATCH`. Leaked data outranks a
broken or mismatched output.

| Code | R/T | Meaning |
|---|---|---|
| `VERIFY_OUTPUT_INVALID` | T | Output does not open or render (PDF), or is not a valid archive/XML package (DOCX). |
| `VERIFY_PAGE_COUNT_MISMATCH` | T | PDF output page count differs from input. |
| `VERIFY_STRUCTURE_MISMATCH` | T | DOCX output is missing parts that the input had and the policy did not remove. |
| `VERIFY_RESIDUAL_FINDING` | T | A source finding is still extractable. |
| `VERIFY_RESIDUAL_DETECTION` | T | Rerun of mandatory detectors found new entities. |
| `VERIFY_RESIDUAL_METADATA` | T | Metadata, attachments, links, or hidden content remain. |
| `VERIFY_REVIEW` | — | Verifier could not decide; review required. |

### Job, storage, security, internal (Stages 3, 12, 14)

| Code | R/T | Meaning |
|---|---|---|
| `JOB_TIMEOUT` | R | Processing exceeded the time limit. |
| `JOB_CANCELLED` | T | Cancelled by HR. |
| `JOB_INTERRUPTED` | R | App stopped during processing and the 3-attempt limit was reached. |
| `STORAGE_WRITE_FAILED` | R | Local write failed (disk full, permissions). |
| `STORAGE_PATH_REJECTED` | T | Path containment check failed. |
| `STORAGE_INTEGRITY_FAILED` | T | Stored file hash does not match. |
| `SECURITY_HOST_REJECTED` | T | Host header not allowed. |
| `SECURITY_ORIGIN_REJECTED` | T | Origin not allowed. |
| `SECURITY_TOKEN_INVALID` | T | Missing or invalid session/CSRF token. |
| `SECURITY_RATE_LIMITED` | R | Too many requests. |
| `INTERNAL_ERROR` | R | Unexpected error; details not exposed. |

Exception to D-06: automatic, bounded retries inside the worker (Stage 12, e.g.
`JOB_INTERRUPTED` after a crash) happen *before* the document becomes terminal and reuse
the retained input. Each attempt deletes any partial output first and produces a new
output id.

Blocking review reasons (`PDF_ENCRYPTED`, `PDF_TOO_MANY_PAGES`, `PDF_NO_TEXT_LAYER`,
`PDF_TEXT_UNRELIABLE`, `DOCX_ENCRYPTED`, `DOCX_TOO_LARGE_TEXT`, `DOCX_NO_TEXT`) put the
document in non-approvable `REVIEW_REQUIRED` (see supported-pdf.md §3) so HR sees
the reason; the only action is delete.

Stage restrictions enforced by the domain: an upload rejection accepts only
`UPLOAD_*`, `DOCX_MACRO_OR_TEMPLATE`, `STORAGE_*`, and `INTERNAL_ERROR`. `fail` accepts,
besides `JOB_TIMEOUT`:
- during validation: validation codes, `STORAGE_*`, and `INTERNAL_ERROR`;
- during processing: `DETECT_*`, `MAP_*`, `REDACT_*`, `STORAGE_*`, and `INTERNAL_ERROR`;
- during verification: `STORAGE_*` and `INTERNAL_ERROR` (verifier findings arrive as
  `VERIFY_*` codes in a FAILED verification result).

`SECURITY_*` codes are request-level only and never become a document's code. `PDF_*`
codes cannot apply to a DOCX job and vice versa, nor can
`VERIFY_PAGE_COUNT_MISMATCH` (PDF only) or `VERIFY_STRUCTURE_MISMATCH` (DOCX only).

## 4. HTTP status (Stage 5)

The JSON body is always `{ "code": "<ErrorCode>" }` plus optional `batch_id`,
`document_id`, and `limit`. There is no message field and no filename. Unknown
batch or document IDs return `404` with `INTERNAL_ERROR` (there is no `NOT_FOUND`
code). Concurrent or illegal transitions return `409` with `INTERNAL_ERROR`.

| Status | Codes |
|---|---|
| 400 | `UPLOAD_UNSUPPORTED_TYPE`, `UPLOAD_SPOOFED_TYPE`, `DOCX_MACRO_OR_TEMPLATE`, `UPLOAD_MALFORMED_REQUEST` |
| 408 | `UPLOAD_TIMEOUT` |
| 409 | `UPLOAD_DUPLICATE`, `UPLOAD_BATCH_CLOSED` |
| 413 | `UPLOAD_FILE_TOO_LARGE`, `UPLOAD_BATCH_FILE_LIMIT`, `UPLOAD_BATCH_SIZE_LIMIT` |
| 500 | `STORAGE_WRITE_FAILED`, `STORAGE_PATH_REJECTED`, `STORAGE_INTEGRITY_FAILED`, `INTERNAL_ERROR` |
