# Masking policy

Status: Stage 0 baseline, approved by tech lead. Implemented as the typed
`MaskingPolicy` in Stage 2. All examples in this document are synthetic; digit
patterns use `X` placeholders so that no real number appears in the repository.

## 1. Principles

1. **Masking is not anonymization.** The policy removes direct identifiers and
   sensitive attributes. Career history remains and can re-identify a person.
2. **Over-redaction beats leakage.** When a detector is unsure whether text is a
   mandatory entity, it redacts and flags for review; it does not skip.
3. **Mandatory entities cannot be disabled** by HR, configuration, or API input.
   The only HR-selectable entity is `SALARY`.
4. **Permanent redaction only.**
   - PDF: every redaction is a PDF redaction annotation that is applied (content removed
     from the content stream), never a drawn rectangle.
   - DOCX: the redacted characters are removed from the XML and replaced with the label
     text. Highlighting, shading, black font color, or hiding text is never redaction.
5. **One policy, two formats.** Detection runs once on a format-neutral text model; the
   same entity catalogue, thresholds, and toggle apply to PDF and DOCX.
6. **Raw values are transient.** Detected text lives only in process memory for the
   duration of a job. Persisted findings carry type, location (PDF page + boxes, or DOCX
   part + range), confidence, detector id/version, replacement label, and review flag —
   never the value.
7. **Verification gates release.** No output is `COMPLETED` without independent
   verification `PASSED` (Stage 11).

## 2. Entity catalogue

`M` = mandatory, `O` = optional (HR toggle), `N` = not handled in the PoC
(accepted residual risk). "Stage" = stage that owns detection. Stage 7 covers
pattern and labeled-field entities; Stage 8 covers contextual/section-based
entities (decision D-14).

| Entity type | M/O | Label | What is redacted | Stage |
|---|---|---|---|---|
| `CANDIDATE_NAME` | M | `[NAME]` | Candidate's name everywhere it appears, including repeated variants, headers/footers, and diacritic-free variants. | 8 |
| `REFERENCE_NAME` | M | `[NAME]` | Names of referees in reference sections. | 8 |
| `EMAIL` | M | `[EMAIL]` | Any email address (candidate or reference). | 7 |
| `PHONE` | M | `[PHONE]` | Mobile and landline numbers (candidate or reference). | 7 |
| `NATIONAL_ID` | M | `[ID]` | CCCD (12 digits), CMND (9 or 12 digits) with context. | 7 |
| `PASSPORT` | M | `[ID]` | Passport numbers with context. | 7 |
| `POSTAL_ADDRESS` | M | `[ADDRESS]` | Residential address, hometown (quê quán), place of origin (nguyên quán), permanent residence (hộ khẩu thường trú), place of birth. | 7 (labeled), 8 (unlabeled, in contact block) |
| `DATE_OF_BIRTH` | M | `[DOB]` | Date of birth, year of birth, and age. | 7 |
| `GENDER` | M | `[REDACTED]` | Value of labeled gender field. | 7 |
| `MARITAL_STATUS` | M | `[REDACTED]` | Value of labeled marital-status field. | 7 |
| `NATIONALITY` | M | `[REDACTED]` | Value of labeled nationality field. | 7 |
| `RELIGION` | M | `[REDACTED]` | Value of labeled religion field. | 7 |
| `ETHNICITY` | M | `[REDACTED]` | Value of labeled ethnicity (dân tộc) field. | 7 |
| `HEALTH` | M | `[REDACTED]` | Labeled health status, height, weight. | 7 |
| `FAMILY_DETAILS` | M | `[REDACTED]` | Content of a family-information section. | 8 |
| `PERSONAL_URL` | M | `[URL]` | LinkedIn, GitHub, Facebook, personal sites/portfolios, and messaging handles (Zalo, Skype, Telegram) in contact context. | 7 |
| `PHOTO` | **N** | — | Not detected or removed in the PoC. Embedded images, including candidate photos, are kept unchanged (D-13). | — |
| `SALARY` | O (default ON) | `[SALARY]` | Current/expected salary values. | 7 |

Kept (not masked): employers, schools/universities, job titles, skills,
certifications, languages spoken, employment and education dates, project
names, city names that appear inside work or education history, a
referee's job title and company, and — as an accepted PoC limitation (D-13) —
all embedded images, including candidate photos.

### Salary toggle

- Scope is **per batch** (Stage 13 "batch-level salary toggle"); default **ON** (masked).
- Salary detectors always run and always produce findings (Stage 7). The toggle only
  controls whether Stage 10 redacts them. When OFF, salary findings are counted but not redacted,
  and the verifier does not treat remaining salary text as a leak.
- The toggle value used for each document is recorded in job metadata.

## 3. Detection cues (Vietnamese and English)

All cues below are *patterns and labels*, not data. Matching is performed on
Unicode NFC text with a parallel diacritic-folded, case-folded view for
matching only; findings always map back to original spans (Stage 9).

### Labels / section headings

| Entity | Vietnamese cues | English cues |
|---|---|---|
| Name | Họ và tên, Họ tên, Tên | Full name, Name |
| Date of birth | Ngày sinh, Sinh ngày, Năm sinh, Tuổi | Date of birth, DOB, Born, Age |
| Gender | Giới tính | Gender, Sex |
| Marital status | Tình trạng hôn nhân, Hôn nhân | Marital status |
| Nationality | Quốc tịch | Nationality |
| Religion | Tôn giáo | Religion |
| Ethnicity | Dân tộc | Ethnicity |
| Health | Sức khỏe, Chiều cao, Cân nặng | Health, Height, Weight |
| Address | Địa chỉ, Chỗ ở hiện nay, Quê quán, Nguyên quán, Hộ khẩu thường trú, Nơi sinh | Address, Hometown, Place of birth, Permanent address |
| National ID | CCCD, CMND, Căn cước công dân, Chứng minh nhân dân, Số CMND/CCCD | ID card, ID number, National ID, Citizen ID |
| Passport | Hộ chiếu, Số hộ chiếu | Passport, Passport No. |
| Salary | Mức lương, Lương mong muốn, Mức lương mong muốn, Lương hiện tại, Thu nhập | Salary, Expected salary, Current salary, Compensation |
| References | Người tham chiếu, Người tham khảo, Người giới thiệu, Thông tin tham chiếu | References, Referees |
| Family | Thông tin gia đình, Quan hệ gia đình | Family, Family background |

### Value shapes (synthetic templates)

| Entity | Shapes | Context required? |
|---|---|---|
| Mobile phone | `0XX XXX XXXX` with prefixes 03/05/07/08/09; `+84 XX XXX XXXX`; `84XXXXXXXXX`; separators space, `.`, `-`; optional `(+84)` | No |
| Landline | `02XX XXX XXXX` | No |
| CCCD | 12 digits, optional spaces | No (12-digit isolated numbers are redacted; over-redaction accepted) |
| CMND | 9 digits | **Yes** — only with an ID label; 9-digit numbers are too common otherwise |
| Passport | 1 letter + 7 digits | **Yes** |
| Date of birth | `dd/mm/yyyy`, `dd-mm-yyyy`, `dd.mm.yyyy`, `ngày dd tháng mm năm yyyy`, `dd Month yyyy`, `yyyy` | **Yes** — dates are common in work history; only labeled dates are DOB |
| Age | `XX tuổi`, `Tuổi: XX`, `Age: XX` | Yes |
| Salary | `XX.XXX.XXX VND`, `XX triệu`, `XXtr`, `X,XXX USD`, `$X,XXX/month`, `Thỏa thuận`, `Negotiable` | **Yes** — salary label or salary section |
| Email | RFC-like `local@domain.tld` | No |

Synthetic example people used in docs and fixtures: **Nguyễn Văn Mẫu**,
**Trần Thị Thử**, **Jane Example**, **John Sample**. Synthetic email domains:
`example.invalid`, `example.test`. Synthetic companies: **Công ty TNHH Ví Dụ**,
**Example Bank Ltd**.

## 4. Confidence and review

| Confidence | Mandatory entity | Salary (toggle ON) |
|---|---|---|
| ≥ 0.85 | Redact | Redact |
| 0.50 – 0.85 | Redact **and** `requires_review` | Redact and `requires_review` |
| < 0.50 | Discard, count as `suppressed_low_confidence` in metadata | Discard |

- Thresholds are initial values. Changing them is a policy change requiring approval.
- A document with any `requires_review` finding ends in `REVIEW_REQUIRED` even if
  verification passes. HR inspects the **masked** output (never extracted text) and approves
  (→ `COMPLETED`) or denies (→ `REJECTED`, output deleted).
- Name detection (Stage 8) must set `requires_review` when there is no explicit label and the
  layout signal is weak.

## 5. Overlap resolution and replacement

- Overlapping findings merge into the union of their boxes; the more specific type wins the
  label (`NATIONAL_ID` > `PHONE`; `EMAIL` > `PERSONAL_URL`). The full order is
  `LABEL_PRIORITY` in `domain/policy.py`.
- PDF mapping (Stage 9) works on whole extracted words. A word only partly inside a finding
  (trailing punctuation, a label glued to its value) is redacted whole. Words on one line
  merge into one box only when no unrelated word lies inside the merged box.
- PDF: a label is drawn only if it fits inside the redaction box at ≥ 6 pt using a built-in
  font (labels are ASCII). Otherwise the box is filled solid black with no label.
  Redaction fill is black; label text is light grey (0.9), not pure white, because the
  hidden-content scan treats white text as invisible. A region that spans several lines
  gets one label, in its box with the largest fitting size; its other boxes are solid.
- PDF redaction rectangles are trimmed vertically so they stop 0.25 pt short of words on
  the lines directly above and below; PyMuPDF removes every glyph a rectangle touches.
- When the salary toggle is OFF, salary findings are still reported but produce no
  redaction region, and they do not count towards low-confidence review.
- DOCX: the label always replaces the text, in the formatting of the first redacted run.
  Every duplicate copy of the text (e.g. text-box fallback) gets the same replacement.
- Field **labels** (e.g. "Giới tính:") remain; only values are redacted, except
  `FAMILY_DETAILS` and reference sections, where the full value block is redacted.

## 6. Non-text components

DOCX equivalents (document properties, thumbnail, field codes, tracked changes,
comments, hidden text, embedded objects, external relationships) are listed in
[supported-pdf.md](supported-pdf.md) §6.3–§6.4 and follow the same rule: always strip
what is pure metadata, and always remove hidden content and report it (D-32).

### PDF

| Component | Action | Shown to HR? |
|---|---|---|
| Document info dictionary and XMP metadata (author, title, subject, keywords, producer) | Always stripped and replaced with neutral values | No |
| Link annotations and URI actions | Always removed (URIs can hold emails/profiles) | No |
| Outlines/bookmarks, page thumbnails, page labels | Always removed | No |
| Tagged-PDF structure (alt text, `StructTreeRoot`, `MarkInfo`) and application private data (`PieceInfo`) | Always removed (D-31); accessibility tags are lost | No |
| Incremental-update history / previous revisions | Output is fully rewritten (garbage-collected, non-incremental save) | No |
| Embedded raster images (including candidate photos) | Kept unchanged; no OCR, no face detection (D-13). Text inside images is not detected. | No |
| Embedded files / attachments / portfolios | Always removed (D-32) | Reported |
| AcroForm fields / XFA forms | Always removed; widget values are lost (D-32) | Reported |
| JavaScript, OpenAction, Launch, and other active actions | Always removed (D-32) | Reported |
| Comment/markup annotations (text notes, highlights, free text, stamps) | Always removed (D-32) | Reported |
| Optional content groups (hidden layers) | Hidden-layer content always removed (D-32) | Reported |
| Invisible text (render mode 3, zero opacity), text outside the crop box, white-on-white or sub-2 pt text | Always removed (D-32) | Reported |

PDF hidden-content removal (Stage 10) is fail-closed:
- Hidden-layer content is cut from the page and form content streams. Each page is
  rendered before and after, and any difference refuses the output
  (`REDACT_SANITIZE_FAILED`). This includes layers whose visibility PDF viewers disagree
  on, such as some membership dictionaries MuPDF draws but the PDF rules hide.
- Invisible, off-crop, white, or tiny text is removed with fill-less redaction
  annotations, so visible glyphs that overlap it are removed too.
- The output is reopened and scanned again; any remaining hidden content, stripped
  catalogue entry, redaction annotation, or text inside a redacted region refuses it.

The hidden-content alert shows only the **kind**, **count**, and **page numbers**
of what was found (for example "2 comment annotations on pages 1, 3; 1 attachment"), never
its contents or attachment filenames. See [supported-pdf.md](supported-pdf.md) §4.

## 7. Policy change control

- Adding a mandatory entity: allowed at any time with tests.
- Removing or making optional a mandatory entity, raising confidence thresholds, or
  changing §6 actions: tech-lead approval, update to this file, and a policy version bump.
- Each job records the policy version it ran under.
