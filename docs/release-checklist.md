# Release-candidate checklist (Stage 16)

This is a **PoC**, not an IT-approved product. Tick only what is true.
Do not attach real CVs or evaluation directories to this list.

## Build and tests

- [ ] `make check` passes on this checkout (file guard, lint, types, UI
      build, pytest, vitest, Playwright).
- [ ] `make eval` produces metadata-only JSON (no values, no paths).
- [ ] `make build` has been run on the target Mac; `cv_masking/static`
      exists.
- [ ] Apple Silicon smoke: `.command` opens `127.0.0.1` UI.
- [ ] Intel x86_64: **untested** — do not claim it.

## Security and privacy

- [ ] Server binds `127.0.0.1` only; Host/Origin/session/CSRF in place
      (Stage 14).
- [ ] No telemetry, CDN, cloud, or outbound AI in runtime code.
- [ ] UI and README say **masked, not anonymized**.
- [ ] Photos/images disclosed as unmasked (D-13).
- [ ] Repository contains no runtime `data/`, no real CVs, no committed
      PDF/DOCX.
- [ ] Authorized evaluation (if any) was run by a human on the HR laptop
      with `CV_MASKING_AUTHORIZED_EVAL=1`; Cursor was not used; only the
      metadata report is kept.

## Licence and distribution

- [ ] Bank legal has confirmed the PyMuPDF **AGPL-3.0 or commercial**
      path — **or** this box stays unchecked and the tree is not copied
      to other HR Macs.
- [ ] Launcher is unsigned / not notarized; Gatekeeper steps are in
      [install.md](install.md).
- [ ] IT understands uninstall is delete the project folder (not
      forensic).

## Product limitations (must be presented)

- [ ] No OCR / image-only CVs.
- [ ] No Windows.
- [ ] No name guarantee: PDF synthetic set misses `family_details` and
      `reference_name` on the labeled htmlbox layout (`make eval`).
- [ ] Verification does not search short generic tokens everywhere
      (D-37).
- [ ] Stored CVs remain until HR deletes them (D-23); Time Machine may
      back up `data/` unless excluded.
- [ ] DOCX rendering in Microsoft Word is not verified.

## Go / no-go notes

Record the date, Mac model, `uname -m`, and whether AGPL is cleared.
Do not record filenames of real CVs.
