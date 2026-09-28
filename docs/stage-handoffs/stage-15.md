# Stage 15 handoff — Local build and launcher

## Stage and objective

Stage 15 is the HR one-command path on macOS: Vite builds the React app into
the Python package, FastAPI serves it on `127.0.0.1`, and
`scripts/cv-masking.command` starts a single instance, waits for health, and
opens the default browser with a one-time bootstrap token that seeds the
Stage 14 session.

Node is not required at runtime. The launcher is unsigned (D-39). PyMuPDF
AGPL is unchanged residual risk. This checkout was tested on Apple Silicon
(arm64, Apple M2). Intel (x86_64) is not tested.

## Architecture decisions

- **Same-origin UI.** `make build` copies `frontend/dist/` to
  `backend/src/cv_masking/static/` (gitignored). FastAPI serves `GET /`,
  `GET /index.html`, and `GET /assets/*` without a session. `/api/*` still
  needs the cookie and CSRF header, except health and the session route.
- **Bootstrap token (D-42).** `--desktop` sets `CV_MASKING_BOOTSTRAP_TOKEN`
  and opens `http://127.0.0.1:<port>/?bootstrap=…`. `GET /api/session` then
  requires that token once, or a valid session cookie afterwards. Dev
  (`make dev`, Playwright) leaves the env unset, so session stays open as in
  Stage 14.
- **Health stays public** so the launcher can poll `/api/health`.
- **Single instance.** Exclusive `fcntl.flock` on `data/lock/instance.lock`.
  If health is already OK, a second start only opens the browser without a
  new token.
- **Bundled Python is a uv venv**, not a frozen binary, so Stage 12
  `multiprocessing` spawn keeps the same interpreter (Stage 12 Q6).
- **Browser open** is `/usr/bin/open` with an argv-only loopback URL. No
  shell. Architecture tests allow `subprocess` and `http.client` only in
  `desktop.py`.
- **Shutdown.** Closing the Terminal window or Ctrl+C stops uvicorn; the
  Stage 12 worker still gets 10 s. `data/` inputs, outputs, and metadata
  stay (D-24). Work leftovers remain the sweeper’s job.
- **Unsigned.** No codesign, no notarization. Gatekeeper: right-click Open.

## Files added/changed

| File | Change |
|---|---|
| `backend/src/cv_masking/api/ui.py` | Resolve/serve packaged Vite build; public path helper |
| `backend/src/cv_masking/api/app.py` | Optional static dir + bootstrap; `create_runtime_app` reads env |
| `backend/src/cv_masking/api/security.py` | `BootstrapGate`; public UI GETs |
| `backend/src/cv_masking/api/session.py` | Require bootstrap when configured |
| `backend/src/cv_masking/desktop.py` | Lock, health wait, `/usr/bin/open`, `run_desktop` |
| `backend/src/cv_masking/__main__.py` | `--desktop`, `--no-browser` |
| `backend/src/cv_masking/config.py` | `CV_MASKING_BOOTSTRAP_TOKEN` |
| `backend/src/cv_masking/adapters/local_storage/root.py` | `lock/` directory |
| `scripts/cv-masking.command` | Double-click launcher |
| `Makefile` | `make build`; `make check` includes it |
| `frontend/src/api.ts`, `frontend/src/App.tsx` | Consume bootstrap query, strip URL |
| `frontend/.prettierignore` | Ignore `dist/` |
| `.gitignore` | Packaged `cv_masking/static/` |
| `docs/install.md` | Install, run, uninstall |
| `README.md`, `SECURITY.md`, `THREAT_MODEL.md`, `docs/{data-retention,product-scope,stage-plan}.md` | Stage 15 / D-42 |
| `backend/tests/api/test_ui.py` | Public HTML/assets, bootstrap once, API still gated |
| `backend/tests/test_desktop.py` | URL allowlist, lock, flags, launcher script |
| `backend/tests/test_ui_bundle.py` | No remote load URLs in the build |
| `frontend/tests/api-session.test.ts` | Bootstrap query stripped |
| `docs/stage-handoffs/stage-15.md` | This file |

No new Python or npm runtime packages. Build still uses the existing Vite
toolchain. `/usr/bin/open` is a macOS subprocess, argv-only, loopback URL.

## Commands run and exact results

- `uname -m` / CPU: **arm64**, Apple M2.
- `make check`:
  - file guard: 211 files checked, none refused;
  - ruff format/check: 158 files, all checks passed;
  - frontend Prettier + ESLint: pass (`dist/` ignored);
  - `mypy --strict`: no issues in 156 source files;
  - `tsc --noEmit`: pass;
  - `make build`: Vite production bundle
    `index.html` 0.44 kB, CSS 1.15 kB, JS 241.90 kB gzip 76.53 kB;
  - pytest: **719 passed** in 78.02 s;
  - vitest: 5 files, **13 passed**;
  - Playwright: **2 passed** in 3.9 s (still Vite + API for e2e).
- Manual: `python -m cv_masking --desktop --no-browser` then
  - `GET /api/health` → 200;
  - `GET /` → HTML `lang="vi"` with `/assets/index-….js` (same origin);
  - `GET /api/session` without bootstrap → 403 `SECURITY_TOKEN_INVALID`;
  - process stopped; port 8765 closed.

## Tests added

- Public `/` and `/assets/app.js` without a session; CSP present;
  `..` in an asset path is not public; `/api/batches/…` still 403.
- Bootstrap: missing/wrong token 403 and not echoed; first matching token
  200; replay without cookie 403; cookie refresh 200.
- Desktop URL builder rejects a hostile token and port 80; flock is
  exclusive; `/usr/bin/open` argv is loopback; missing UI exits; existing
  health opens the browser with no new token; `--desktop --reload` refused;
  `--desktop --no-browser` calls `run_desktop(open_browser=False)` on
  127.0.0.1; `.command` is executable and has no `https://`.
- Packaged UI: HTML/CSS have no remote URLs; JS may only contain React
  error-decoder and W3C namespace strings (not loaded as scripts).
- Frontend: `consumeBootstrapQuery` strips the token from the query.

## Security/privacy review

- Loopback bind unchanged. Host/Origin/CSRF unchanged for `/api`.
- No CDN, fonts, or telemetry in `index.html`. Bundle scan on the copied
  static tree.
- Bootstrap is not logged. Access log remains off. Token is url-safe and
  compared with `hmac.compare_digest`.
- `/usr/bin/open` receives only a validated `http://127.0.0.1:<port>/`
  URL.
- Lock and pid file are under `data/lock/` (0600/0700), gitignored.
- Shutdown does not delete CVs (D-24). Uninstall is delete the project
  folder.
- Playwright still uses Vite; production session gating is covered by
  pytest and the manual curl above.

## Known limitations

- **Unsigned / not notarized.** Gatekeeper warning on first open.
- **AGPL.** PyMuPDF licence path is still for bank legal (D-39).
- **Intel Macs untested.** Install on the target machine; do not copy
  `.venv` across architectures.
- **Bootstrap in history.** The first URL may remain in browser history
  after the query is stripped; the token is single-use.
- **Node still needed to build**, not to run.
- **Two-click if `make dev` is up.** Health already 200 → launcher opens
  `/` without a new bootstrap. Quit `make dev` before a desktop demo.
- **React `https://react.dev/errors/` strings** remain inside the minified
  JS. They are not requested unless React throws in production.

## Manual verification steps

1. `make check`
2. Quit `make dev` if it is running.
3. Double-click `scripts/cv-masking.command` (or
   `backend/.venv/bin/python -m cv_masking --desktop`).
4. Confirm the UI is Vietnamese, same origin (`127.0.0.1:8765`), no Node
   process. Use **synthetic** files only.
5. Close the Terminal window; confirm port 8765 is free; `data/` still
   exists.
6. Uninstall dry-run: read [docs/install.md](../install.md); do not delete
   this checkout unless you intend to.

Do not use real CVs. Do not open `data/`.

## Questions/decisions for the tech lead

D-42 is recorded (venv, bootstrap, public health, AGPL residual, Apple
Silicon). Still open:

1. **AGPL / IT install.** When legal confirms, can IT copy this tree onto
   HR Macs as the PoC install?
2. **Intel.** Should Stage 16 include an x86_64 smoke run?
3. **Codesign.** Out of scope here; still a later decision if this leaves
   the PoC laptop.

## Suggested commit message

`feat(desktop): serve the built UI from FastAPI and add an unsigned macOS launcher (Stage 15)`
