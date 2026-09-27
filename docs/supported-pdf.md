# Supported input definition (PDF and DOCX)

Status: Stage 0 baseline. Upload checks are enforced in Stage 5, structural
checks in Stage 6 (PDF) and Stage 6b (DOCX), hardening limits in Stage 14.
§1–§5 cover PDF; §6 covers DOCX.

## 1. Accepted file types

| Type | PoC status |
|---|---|
| PDF (`application/pdf`, magic bytes `%PDF-`) | Accepted if it passes §2–§4. Output: `redacted-<uuid>.pdf`. |
| DOCX (Word 2007+ `.docx`, ZIP container with a WordprocessingML main part) | Accepted if it passes §6. Output: `redacted-<uuid>.docx` (D-15). |
| Legacy `.doc`, `.rtf`, `.odt`, `.pages` | Rejected with `UPLOAD_UNSUPPORTED_TYPE`. |
| Macro-enabled `.docm`, templates `.dotx`/`.dotm` | Rejected with `DOCX_MACRO_OR_TEMPLATE`. |
| Images (JPG, PNG, HEIC, scans) | Rejected with `UPLOAD_UNSUPPORTED_TYPE`. |
| Anything else | Rejected with `UPLOAD_UNSUPPORTED_TYPE`. |

Extension and client-supplied content type are advisory; **content decides**.
- PDF: `%PDF-` within the first 1024 bytes.
- DOCX: ZIP local-file-header magic, a `[Content_Types].xml` entry, and a main document part
  whose content type is `application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml`.
- A file whose extension or content type disagrees with its content is rejected with
  `UPLOAD_SPOOFED_TYPE`.

## 2. Limits (configurable, with hard caps)

| Limit | Default | Enforced at | Error code |
|---|---|---|---|
| File size | 20 MB | Upload (streamed, no full buffering) | `UPLOAD_FILE_TOO_LARGE` |
| Files per batch | 50 (D-30) | Upload | `UPLOAD_BATCH_FILE_LIMIT` |
| Total batch size | 500 MB (proposed, Q-06) | Upload | `UPLOAD_BATCH_SIZE_LIMIT` |
| Pages per document | 30 | Validation | `PDF_TOO_MANY_PAGES` |
| Extractable characters per page | 8 (Stage 6) | Validation | `PDF_NO_TEXT_LAYER` |
| Zero pages | — | Validation | `PDF_NO_PAGES` |
| Decompressed stream size / object count | set in Stage 14 | Validation | `PDF_RESOURCE_LIMIT` |
| Per-document processing time | set in Stage 12 | Worker | `JOB_TIMEOUT` |

## 3. Structural classification

A PDF is **supported** when all of the following hold:

1. It opens with the approved parser without repair warnings that change page count.
2. It is not encrypted (neither user nor owner password).
3. It has 1–30 pages.
4. Every page has an extractable text layer (at least a minimum number of
   extractable characters per page, set in Stage 6), with valid Unicode mapping for the text
   (no missing ToUnicode on the fonts used for body text).
5. It contains no hidden content from §4, or HR has approved the hidden-content alert.

| Condition | Resulting state | Code | HR actions |
|---|---|---|---|
| Not parseable / corrupt | `FAILED` | `PDF_MALFORMED` | Delete |
| Zero pages | `FAILED` | `PDF_NO_PAGES` | Delete |
| Encrypted | `REVIEW_REQUIRED` | `PDF_ENCRYPTED` | Delete (remove password outside the tool and re-upload) |
| Too many pages | `REVIEW_REQUIRED` | `PDF_TOO_MANY_PAGES` | Delete |
| Any page without a text layer (image-only / scanned) | `REVIEW_REQUIRED` | `PDF_NO_TEXT_LAYER` | Delete. No output is produced. |
| Unmappable glyphs (text cannot be reliably extracted) | `REVIEW_REQUIRED` | `PDF_TEXT_UNRELIABLE` | Delete |
| Hidden content (§4) | `REVIEW_REQUIRED` | `PDF_HIDDEN_CONTENT` | **Approve** (continue; content removed) or **Deny** |

`REVIEW_REQUIRED` for encryption, page count, image-only, and unreliable text is
**not approvable**: approving would produce an output the verifier cannot vouch
for. Only `PDF_HIDDEN_CONTENT` and low-confidence findings can be approved.

## 4. Hidden content

"Hidden content" is any content that a reader would not see on the rendered page
but that can be extracted or executed:

- Embedded files, attachments, portfolios.
- AcroForm fields and XFA forms.
- JavaScript and active actions (OpenAction, Launch, SubmitForm, ImportData).
- Comment and markup annotations (text notes, pop-ups, free text, stamps, highlights with contents).
- Optional content groups set to hidden.
- Invisible text (render mode 3), text outside the crop box, text whose fill matches the
  background, and text below 2 pt.

The alert payload contains only: category, count, and page numbers. It never
contains the hidden text, annotation contents, attachment names, or script source.

On **approve**, all flagged hidden content is removed from the output, the
document goes through normal detection/redaction, and the verifier checks that none of
the flagged categories remain. On **deny**, the job becomes `REJECTED` and its files are
deleted per [data-retention.md](data-retention.md).

Always-stripped components (metadata, links, outlines, thumbnails) are removed
without alerting; see [masking-policy.md](masking-policy.md) §6. Embedded images are
kept unchanged in the PoC (D-13) and are not treated as hidden content.

## 5. Synthetic fixture matrix (to be generated in Stage 6)

Single-column, two-column, table layout, header/footer repeats, Vietnamese
diacritics (NFC and NFD), bilingual, encrypted, zero-page, 31-page, image-only
page, malformed header, truncated xref, each hidden-content category, links,
metadata with synthetic author, embedded synthetic image (must survive unchanged). All generated from
synthetic text at test time or committed as `synthetic-*.pdf`.

## 6. DOCX

### 6.1 Archive and parser safety (fail closed)

A DOCX is a ZIP archive of XML parts; it is untrusted input at both layers.

| Check | Default (finalized in Stage 6b; Stage 14 may tighten) | Code |
|---|---|---|
| File size (compressed) | 20 MB (same as PDF) | `UPLOAD_FILE_TOO_LARGE` |
| Total uncompressed size | 100 MB | `DOCX_RESOURCE_LIMIT` |
| Per-entry uncompressed size | 50 MB | `DOCX_RESOURCE_LIMIT` |
| Entry count | 2,000 | `DOCX_RESOURCE_LIMIT` |
| Per-entry compression ratio | 100:1 | `DOCX_RESOURCE_LIMIT` |
| Entry names | Reject absolute paths, `..`, backslashes, drive letters, duplicates, NUL | `DOCX_UNSAFE_ARCHIVE` |
| Archive never extracted to disk | Parts are read in memory, bounded by the limits above | — |
| XML parsing | No DTDs, no entity resolution, no network, no XInclude, bounded depth/size | `DOCX_MALFORMED` |
| Encrypted/password-protected (stored as an OLE compound file, magic `D0 CF 11 E0`) | Not processed | `DOCX_ENCRYPTED` |
| Extracted text length | 300,000 characters (stand-in for the 30-page PDF limit; Word page count is not reliable without rendering) | `DOCX_TOO_LARGE_TEXT` |
| No extractable text | — | `DOCX_NO_TEXT` |

### 6.2 Content that is extracted, detected, and redacted

All of these are visible content and go through the shared detectors:
main body, tables, headers, footers, footnotes, endnotes, text boxes and shapes
(**both** the `mc:AlternateContent` Choice and Fallback copies), content controls,
and the displayed result of fields.

### 6.3 Always stripped (no alert)

| Component | Why |
|---|---|
| Core, app, and custom document properties (`docProps/*`: creator, last modified by, title, company, manager, custom fields) | Often contain the candidate's name. |
| Thumbnail (`docProps/thumbnail.*`) | It is a picture of page 1. |
| Hyperlink targets (relationship `Target` of hyperlinks, including `mailto:`) | Hold emails and profile URLs; the visible text is redacted separately. |
| Field codes (`w:instrText`) | Can hold hidden values; the displayed result text is kept and scanned. |
| Image alt text and titles (`wp:docPr` `descr`/`title`) | Can hold names. Images themselves are kept (D-13). |
| Tracked-change and comment author lists (`people.xml`, author attributes) | Names. |
| Attached template path and document variables (`settings.xml`) | Paths can contain the OS user name. |
| Revision-session ids (`rsid*`) | Linkable metadata. |

### 6.4 Hidden content (alert HR, approve or deny)

| Category | On approve |
|---|---|
| Tracked changes (`w:ins`, `w:del`, moves, formatting changes) | All changes are accepted: deleted text is dropped, inserted text is kept and scanned. |
| Comments (`comments*.xml` and anchors) | Removed. |
| Hidden text (`w:vanish`, `w:specVanish`) | Removed. |
| Embedded objects and packages (`word/embeddings/*`, OLE) | Removed. |
| Imported chunks (`altChunk`: HTML/RTF/MHT inside the DOCX) | Removed. |
| Custom XML parts and data bindings | Removed. |
| Glossary / building-block document | Removed. |
| External relationships other than hyperlinks (linked images, linked OLE, remote template, `INCLUDETEXT`/`INCLUDEPICTURE`) | Removed. These could make Word fetch a remote resource when HR opens the output. |

The alert shows only category, count, and (for DOCX) the part type, such as
"header" or "footnotes", never the content. On **deny** the job becomes `REJECTED`.

### 6.5 Fixture matrix (Stage 6b)

Generated at test time from synthetic text: Vietnamese NFC/NFD, bilingual,
a name split across several runs, tables, headers/footers, footnotes, text box with
AlternateContent fallback, each hidden-content category, each always-strip
item, hyperlinks, field codes, an embedded image with alt text, zip-bomb ratio,
path-traversal entry name, DTD/entity payload, encrypted container, `.docm`, and a
PDF renamed to `.docx`.
