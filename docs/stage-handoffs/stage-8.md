# Stage 8 handoff — Candidate and reference names

## Stage and objective

Stage 8 adds explainable, rule-based detection of `CANDIDATE_NAME` and
`REFERENCE_NAME`, plus the approved D-14 additions: `FAMILY_DETAILS` sections
and unlabeled `POSTAL_ADDRESS` in the header/contact block. Everything runs
in-process on the format-neutral text model. No model, remote call, or new
dependency is added. Nothing is redacted, and the detector is still not wired
into `start_batch` (Stage 12 does that).

## Architecture decisions

- **Provenance on every result.** `TextMatch` gains `signals`, a tuple of rule
  names drawn from a fixed allowlist (`ports.detection.SIGNALS`).
  `CANDIDATE_NAME`, `REFERENCE_NAME`, and `FAMILY_DETAILS` must have at least one
  signal, or construction raises `InvariantError`. An unknown string,
  including a lowercase name, is rejected, so signals cannot carry text.
  `DETECTOR_VERSION` is now `1.1.0`.
- **Line-based sections (`sections.py`).** Headings are whole lines (optional
  bullet, optional trailing colon, bilingual pairs such as "Học vấn /
  Education"). Reference and family headings may also be inline ("Family: …").
  These sections replace the Stage 7 substring search for reference ranges.
- **Name rules (`names.py`)**. Each rule's confidence is fixed:

  | Rule | Detector id | Signals | Confidence |
  |---|---|---|---|
  | Name label ("Họ và tên", "Họ tên", "Tên", "Full name", "Name") with name-shaped value | `name.label` | `label` | 0.95 |
  | Same label with an unusual value shape | `name.label` | `label`, `shape_mismatch` | 0.75 (review) |
  | Header line: first 6 non-empty lines before the first heading, on PDF page 1 / DOCX body / DOCX header parts | `name.header` | `top_of_page` (0.55) + `first_line` (+0.05) + `vn_surname` (+0.10) + `largest_font` (+0.20, PDF box height) + `email_match` (+0.15) | capped at 0.95 |
  | Repeats of an anchor anywhere: exact, diacritic-free, case-folded, family-name-first/last, first+last | `name.repeat` | anchor's signals + `repeat` | anchor's |
  | Reference section: honorific (Ông/Bà/Anh/Chị/Mr/Ms/Dr …) + name | `reference_name.honorific` | `reference_section`, `honorific` | 0.90 |
  | Reference section: name-shaped line start | `reference_name.line` | `reference_section`, `line_start` | 0.75 (review) |
  | Name label inside a reference section | `reference_name.label` | `reference_section`, `label` | 0.95 / 0.75 |

  A name has 2–5 title-case or all-caps tokens. Candidates are rejected when a
  token is an organisation, education, or title word (Ltd, Bank, University,
  Engineer, TNHH, …), when the text contains a phrase such as "công ty", "đại
  học", "ngân hàng", "thành phố", "Hồ Chí Minh", "curriculum vitae", or
  "chuyên viên", or when the line is a section heading. A segment containing a
  label colon is never a header name.
- **Uncertain cases fail to review.**
  - A header name without font-size or email corroboration scores 0.60–0.70,
    which puts it in the review band.
  - `DetectionService` adds `DETECT_LOW_CONFIDENCE` when no `CANDIDATE_NAME`
    finding exists, because every CV names its candidate. See the questions for
    the tech lead.
- **Family (`context.py`).** The whole content block after a family heading, up
  to the next heading, is one `FAMILY_DETAILS` hit (0.90, `section_heading`).
  Stage 7 hits fully inside the block are absorbed.
- **Contact-block address.** Segments in the first 15 lines before the first
  heading are split on `|`, `•`, `·`, `;`, or a spaced dash. Segments with a
  colon, `@`, or phone-length digits are skipped. The rule then counts distinct
  address cues (số, đường, phường, quận, street, ward, district, …):
  - two or more cues plus a house number: 0.88;
  - two or more cues without a number: 0.75 (review);
  - one cue plus a number: 0.70 (review).
- **Overlap resolution (`hits.py`).** Same-type hits merge to the union, and the
  merged hit combines both sets of signals. A hit of a different type is dropped
  only when another hit fully contains it. Partial overlaps are both kept, so no
  characters lose coverage (masking-policy §5 union rule).

## Stage 7 fixes included

- **"đ" folding bug.** `fold_with_map` did not map "đ"/"Đ" to "d" (the letter
  has no Unicode decomposition). As a result, the Stage 7 labels "Địa chỉ" and
  "Điện thoại" never matched when written with the letter. The fix is in, and
  `test_labeled_vietnamese_name_is_exact_and_confident` covers it.
- **Silent PDF drop.** A PDF match with no overlapping word boxes was dropped
  without any signal. It now adds `MAP_AMBIGUOUS` so the document goes to
  review. Stage 9 still owns proper mapping.
- **Weak test.** The Stage 7 low-confidence test could return early without
  asserting anything. It now asserts the review band deterministically.

## Files added/changed

Added:
- `backend/src/cv_masking/adapters/detection/{hits,sections,names,context}.py`
- `backend/tests/application/{synthetic_names,test_names}.py`
- `docs/stage-handoffs/stage-8.md`

Changed:
- `backend/src/cv_masking/adapters/detection/detector.py`: uses shared hits, sections, and the new rules; version 1.1.0
- `backend/src/cv_masking/adapters/detection/normalize.py`: "đ" folding; `Sequence` mapping
- `backend/src/cv_masking/ports/detection.py`: `signals`, `SIGNALS`, `PROVENANCE_REQUIRED`
- `backend/src/cv_masking/application/detection.py`: review when no candidate name or unmappable PDF match
- `backend/tests/application/test_detect.py`: deterministic low-confidence test
- Docs: `README.md`, `docs/stage-plan.md`

## Commands run and exact results

| Command | Result |
|---|---|
| `make check` (guard, lint, typecheck, test) | exit 0 |
| `scripts/check-repo-files.sh --all` | `140 file(s) checked, none refused.` |
| `ruff format` / `ruff check src tests` | `101 files left unchanged` / `All checks passed!` |
| `mypy src tests` (strict) | `Success: no issues found in 101 source files` |
| `python scripts/run_pytest.py` | `263 passed` |
| `vitest run` | `3 passed (3)` files, `7 passed (7)` tests |

## Tests added

Forty new backend tests (223 → 263), all in `test_names.py`:

- **Labeled names:** a Vietnamese name with diacritics, including the "Đ" label
  fold; an English name cut at `|`; a lowercase value that goes to review
  (`shape_mismatch`).
- **Layout:** a PDF title found by largest font (≥ 0.85), with a diacritic-free
  repeat and a reordered short form on page 2 that map to boxes.
- **Header corroboration:**
  - a DOCX header without an email match goes to review;
  - a matching email lifts it to ≥ 0.85;
  - an English header without signals goes to review;
  - an all-caps name in a DOCX header part repeats into the body.
- **Negatives (13 cases, ids `confounder_N`):**
  - company and bank names;
  - university names in Vietnamese and English;
  - job titles;
  - city names;
  - "CURRICULUM VITAE" and "Sơ Yếu Lý Lịch";
  - headings.

  Each yields no name and a review. A second test places company, title, and
  education lines after their headings; only the labeled name is found.
- **References:**
  - honorific (≥ 0.85) and line-start (review) referees;
  - companies on the same lines stay uncovered;
  - `email.reference`;
  - a labeled referee under "References".
- **Family:** the block span is exact and absorbs inner hits; inline "Family:"
  headings work.
- **Contact-block address:**
  - Vietnamese and English addresses are exact spans at ≥ 0.85;
  - the same address after a heading is ignored;
  - a weak address goes to review;
  - a city alone is not an address.
- **Review triggers:** no candidate name, or a PDF match without boxes.
- **Provenance invariant:** each heuristic type without signals raises; an
  unknown signal raises.
- **Bilingual corpus:** exact span precision and recall of 1.0 for the name,
  repeat, address, family, and referee spans; the university is not covered.
- **Provenance and threshold consistency** on the corpus.
- **No values** in `repr(findings/matches)` or logs.
- **Hypothesis:** labels × approved synthetic name tokens × casing × colon
  variants (including full-width). The name is always the exact span at
  ≥ 0.85.

## Security/privacy review

- **No remote I/O, models, or new dependencies.** Name rules are regexes,
  token lists, and box heights. Sockets stay blocked in tests. The bind host
  remains `127.0.0.1`.
- **No text leaves the detector.**
  - `Hit`, `NameAnchor`, and `TextMatch` hold offsets and rule names only.
  - `NameAnchor.tokens` is transient: in memory during one `detect` call.
  - Signals come from a closed allowlist.
  - Logs remain counts.
- **Fixtures** use only the policy people (Nguyễn Văn Mẫu, Trần Thị Thử, Jane
  Example, John Sample), the companies Công ty TNHH Ví Dụ / Example Bank Ltd,
  invented "Ví Dụ" / "Example" institutions, and `example.test` /
  `example.invalid` emails. Test ids are types or indexes.
- **The agent never read, listed, or searched `data/`.**
- **Layering.** The new modules live in `adapters/detection`. The application
  layer imports only ports and the domain.

## Known limitations

- **Header scoring is heuristic.**
  - An English-only header with no matching email or font signal always goes
    to review. This is intentional.
  - A PDF whose name is not the largest text relies on label, surname, or email
    signals.
- **Names of unusual shape are not header candidates** (lowercase, a single
  token, more than five tokens). They reach review through the "no candidate
  name" rule, not through a finding.
- **Repeats are exact token variants.** Initials ("N. V. Mẫu"), nicknames, and
  names split across PDF lines are not matched.
- **Non-name organisation or place words** that are not in the exclusion lists
  can be taken as header names. The exclusion lists live in `names.py`.
- **Family and reference sections end at the next recognised heading.** An
  unknown heading extends the family block, which over-redacts.
- **Not wired into the API or worker** (Stage 12). PDF box mapping is still
  overlap-only (Stage 9).

## Manual verification steps

1. `make check` passes.
2. Read `test_names.py` for the synthetic cases. Do not run the detector on a
   real CV.

## Questions/decisions for the tech lead

1. **No candidate name means review.** A document with no `CANDIDATE_NAME`
   finding gets `DETECT_LOW_CONFIDENCE`. This fails closed, but it will send
   some legitimate CVs to review. Keep it, or narrow it later with evaluation
   data?
2. **Partial cross-type overlaps are now both kept** (previously the lower
   priority was dropped). This matches the §5 union rule. Confirm that the
   Stage 10 redactor redacts the union of overlapping findings.
3. **MAP_AMBIGUOUS for unmappable PDF matches** is raised early here instead of
   waiting for Stage 9. Is that acceptable?

## Suggested commit message

```text
feat(detect): add candidate/reference name, family, and contact-address heuristics (Stage 8)

- Explainable signals on every heuristic result; uncertain cases fail to review
- Fix "đ" label folding and silent drop of unmappable PDF matches
```
