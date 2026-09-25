# Stage 1 handoff — Repository and quality gates

## Stage and objective

Stage 1 sets up reproducible Python 3.12 and TypeScript development:
- One command starts development (`make dev`).
- One command is the quality gate (`make check`).
- The backend has a health endpoint on `127.0.0.1` only.
- The frontend is a minimal static page.

There is no upload handling and no personal-data logic.

**Status: complete and committed.**

## Architecture decisions

- **Backend layout.** `backend/` is a `uv` project with source in `src/cv_masking/`.
  - It uses the `uv_build` build backend and requires Python `>=3.12,<3.13`.
  - `.python-version` is set to `3.12`.
  - `uv.lock` pins every package with hashes.
- **Host is not configurable.**
  - `config.LOOPBACK_HOST = "127.0.0.1"` is a constant, and `Settings.host` is a
    read-only property that returns it.
  - Only the port can be configured, through `CV_MASKING_PORT` (default 8765). It must be
    ASCII digits in the range 1024–65535, otherwise `ConfigError` is raised before the
    server starts.
  - The entry point (`python -m cv_masking [--reload]`) accepts no `--host` or `--port` flag.
- **Uvicorn settings.**
  - Started from code with `host=settings.host`.
  - `proxy_headers=False`, so forwarded-for headers aren't trusted.
  - `server_header=False`.
  - `access_log=False`: request logging waits for Stage 14's metadata-only logging.
  - In reload mode, only the package directory is watched.
- **API docs are off.** `docs_url`, `redoc_url`, `openapi_url` and the OAuth2 redirect are
  all `None`. FastAPI's docs pages load scripts from a public CDN, which the
  no-remote-assets rule forbids.
- **Health endpoint.** `GET /api/health` returns `{"status": "ok", "version": "0.1.0"}`.
  The response model has `extra="forbid"`.
- **Layer packages not created yet.** I didn't create empty `domain/`, `ports/` or
  `adapters/` packages; they'd be placeholder code. Stage 2 creates them with their import rules.
- **Frontend.** Vite 8 + React 19 + TypeScript 6 in `frontend/`.
  - Dev server `127.0.0.1:5173` and preview `127.0.0.1:4173`, both with `strictPort`.
  - `/api` is proxied to `http://127.0.0.1:8765`.
  - The page is static and makes no requests. It uses system fonts and has no favicon or images.
- **npm settings.** `.npmrc` sets `update-notifier=false` (stops npm's background version
  check), `fund=false` and `engine-strict=true`.
- **Makefile targets:** `install`, `dev` (`make -j2` over both servers; Ctrl-C stops
  both), `fmt`, `lint`, `typecheck`, `test`, `check`.
- **Warnings are errors in pytest** (`filterwarnings = error`). The one exception is
  pytest-socket's intentional "a test tried to use socket" warning.
- **Tests can't reach the network.** pytest runs with `--disable-socket --allow-unix-socket`.
  Unix sockets are allowed because asyncio's event loop uses a local socket pair; that isn't
  network access.

## Files added/changed

| File | Change |
|---|---|
| `Makefile` | Added |
| `README.md` | Status updated; development section added |
| `docs/stage-plan.md` | Stage 1 status set to complete |
| `backend/pyproject.toml`, `backend/uv.lock`, `backend/.python-version`, `backend/README.md` | Added |
| `backend/src/cv_masking/{__init__,__main__,config}.py`, `backend/src/cv_masking/api/{__init__,app,health}.py` | Added |
| `backend/tests/test_{config,entrypoint,health,network_guard}.py` | Added |
| `frontend/package.json`, `frontend/package-lock.json`, `frontend/.npmrc` | Added |
| `frontend/{vite.config.ts,tsconfig.json,eslint.config.js,.prettierrc.json,.prettierignore,index.html}` | Added |
| `frontend/src/{main.tsx,App.tsx,styles.css}` | Added |
| `frontend/tests/{setup.ts,App.test.tsx,vite-config.test.ts,no-remote-urls.test.ts}` | Added |
| `docs/stage-handoffs/stage-1.md` | Added (this file) |

## Dependencies (security and packaging impact)

Everything is downloaded at install time only; nothing makes network calls at runtime.

| Package | Version | Scope | Notes |
|---|---|---|---|
| Python (uv-managed) | 3.12.12 | toolchain | One-time download of a standalone CPython build by `uv python install 3.12`, checksum-verified by uv, stored under `~/.local/share/uv/python`. |
| fastapi | 0.141.1 | runtime | MIT, pure Python. Brings starlette 1.7.0 and pydantic 2.13.5 (pydantic-core is native code). |
| uvicorn | 0.53.0 | runtime | BSD. **No `[standard]` extras**, so no uvloop, httptools or watchfiles native binaries. Reload uses its built-in file poller. |
| pytest | 9.1.1 | dev | — |
| pytest-socket | 0.8.1 | dev | Blocks real sockets in tests; includes type hints. |
| httpx2 | 2.13.1 | dev | Starlette 1.7's `TestClient` names `httpx2` as its client in its own package metadata; plain `httpx` now raises a deprecation warning. Brings `truststore` (uses the OS certificate store; unused, because tests make no network calls). |
| ruff | 0.16.9 | dev | Native binary. |
| mypy | 2.3.1 | dev | — |
| react, react-dom | 19.3.0 | frontend runtime | MIT. |
| vite | 8.3.1 | frontend dev | Includes `fsevents` 2.3.3 (optional, macOS file watching). |
| @vitejs/plugin-react | 6.1.1 | frontend dev | — |
| typescript | 6.0.3 | frontend dev | — |
| vitest, jsdom | 5.0.1, 29.1.1 | frontend dev | — |
| @testing-library/react, /dom, /jest-dom | 16.3.3, 10.4.2, 7.0.1 | frontend dev | — |
| eslint, @eslint/js, typescript-eslint, eslint-plugin-react-hooks, globals | 10.11.0, 10.0.1, 8.70.1, 7.1.1, 17.12.0 | frontend dev | — |
| prettier | 3.9.9 | frontend dev | — |
| @types/node, @types/react, @types/react-dom | 26.6.2, 19.3.0, 19.3.0 | frontend dev | — |

npm install results:
- `npm install` reported `found 0 vulnerabilities`, and `npm query` found no packages with
  pre-install, install or post-install scripts.
- On `npm ci`, npm 11 warned that `fsevents@2.3.3` has install scripts not covered by
  `allowScripts`, and did not run them.
- `fsevents` ships a prebuilt `fsevents.node`; its scripts only rebuild it from source.
  I didn't approve them. `npm install-scripts ls` reports `No packages with unreviewed install scripts`.

## Commands run and exact results

1. `uv python install 3.12`: `Installed Python 3.12.12 in 2m 35s`
   (`cpython-3.12.12-macos-aarch64-none`).
2. `uv add fastapi uvicorn`, `uv add --dev pytest pytest-socket ruff mypy httpx2`. I added
   `httpx` first, then removed it after Starlette's deprecation warning (see above).
3. `npm install react react-dom` and `npm install -D …`: `added 232 packages …
   found 0 vulnerabilities`.
4. First `make check`: failed at `prettier --check` (`tests/vite-config.test.ts` formatting).
   Fixed with `make fmt`.
5. Earlier backend-only run: mypy reported `Module "cv_masking.__main__" does not
   explicitly export attribute "uvicorn"` in a test. Fixed by patching `uvicorn.run` on
   the `uvicorn` module.
6. **Final** `make install`: exit 0. **Final** `make check`: exit 0.
   - `ruff format --check`: `11 files already formatted`
   - `ruff check`: `All checks passed!`
   - `prettier --check`: `All matched files use Prettier code style!`
   - `eslint . --max-warnings=0`: no output (clean)
   - `mypy` (strict): `Success: no issues found in 10 source files`
   - `tsc --noEmit`: no output (clean)
   - `pytest`: `37 passed in 0.35s`; 0 skipped, 0 warnings
   - `vitest run`: `Test Files 3 passed (3)`, `Tests 7 passed (7)`
7. Scanner mutation test: I added a temporary `src/zz-probe.ts` containing
   `https://cdn.example.invalid/font.css`.
   - The URL test failed as expected: `expected [ { file: 'src/zz-probe.ts', …(1) } ] to deeply equal []`.
   - The probe file was deleted.
8. `make dev` smoke test, all in one shell invocation. My command sandbox gives each
   invocation its own network namespace, so a first attempt from a separate invocation
   couldn't reach the servers.
   - `curl -i http://127.0.0.1:8765/api/health`: `HTTP/1.1 200 OK`, body
     `{"status":"ok","version":"0.1.0"}`, no `server` header.
   - `curl http://127.0.0.1:5173/api/health` (through the Vite proxy): `{"status":"ok","version":"0.1.0"}`
   - `curl http://127.0.0.1:8765/docs`: `404`
   - `curl http://127.0.0.1:5173/`: `<title>CV Masking</title>`
   - `lsof -iTCP:8765 -iTCP:5173 -sTCP:LISTEN`: only `TCP 127.0.0.1:8765 (LISTEN)` (Python
     reloader and worker) and `TCP 127.0.0.1:5173 (LISTEN)` (node).
   - `curl` to the Mac's LAN address `172.20.10.3` on ports 8765 and 5173: curl exit 7
     (connection refused) on both.
   - Servers stopped afterwards.
9. Commit review with `git add -A -n`: 33 files. No document, image, data, log, cache,
   `node_modules` or `.venv` paths. No remote URLs in tracked code or config (lockfiles and
   Markdown excluded).

## Tests added

| Test | What it proves |
|---|---|
| `test_health.py` (7) | Health returns exactly `{status, version}`; POST → 405; `/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect` → 404; unknown route → 404 |
| `test_config.py` (21) | Host is `127.0.0.1`. Default port 8765. Ports 1024, 8765 and 65535 accepted. 11 invalid ports rejected (zero, privileged, below/above range, negative, empty, surrounding spaces, non-numeric, float, non-ASCII digits). A boolean port is rejected. `CV_MASKING_HOST`, `HOST` and `UVICORN_HOST` set to `0.0.0.0` are ignored. Settings are immutable. |
| `test_entrypoint.py` (7) | `uvicorn.run` gets the app factory, `host="127.0.0.1"`, port 8765, reload off, proxy headers off, server header off and access log off. `--reload` watches only the package. Hostile host environment variables are ignored. The port comes from the environment. An invalid port fails before the server starts. `--host` and `--port` flags are rejected (exit 2). |
| `test_network_guard.py` (2) | Creating an `AF_INET` socket, and connecting to TEST-NET address `192.0.2.1:443`, both raise `SocketBlockedError` |
| `App.test.tsx` (2) | The page heading renders; the local-only statement renders |
| `vite-config.test.ts` (3) | Dev and preview hosts are `127.0.0.1` with `strictPort`; the proxy target is only `http://127.0.0.1:8765` |
| `no-remote-urls.test.ts` (2) | No URL other than `127.0.0.1` in `index.html`, `vite.config.ts` or `src/**`; the scan really covers those files |

## Security/privacy review

- **No personal-data code paths.** No uploads, no file I/O, nothing persisted, no document handling.
- **Network.**
  - Backend and frontend listen on `127.0.0.1` only, verified with `lsof`, and the LAN address is refused.
  - There's no outbound code. Tests block sockets.
  - Frontend sources are scanned for remote URLs.
  - FastAPI's CDN-backed docs are off.
- **Logs.** The uvicorn access log is off. Startup logs show only the bind address and process ids.
- **Supply chain.**
  - Two lockfiles: `uv.lock` with hashes, and `package-lock.json` with integrity hashes.
  - No install scripts were run.
  - uvicorn is installed without native extras.
  - Every dependency is listed above.
- **Scope.** No Stage 14 controls were added early (Host/Origin checks, CSRF, security
  headers, CSP), and no Stage 2 domain code.

## Known limitations

- **Vite dev server Host check.** Vite 8's own allowed-hosts check is left at its default.
  The backend has no Host-header check yet; that's Stage 14.
- **No CSP yet.** Vite's dev server needs inline scripts for hot reload. CSP will be served
  by FastAPI once it serves the built app (Stages 14 and 15).
- **Fixed proxy port.** The Vite proxy target is fixed at port 8765. If `CV_MASKING_PORT`
  is changed, the proxy has to be edited too.
- **Reload uses file polling** (StatReload), because `watchfiles` was deliberately left out.
- **`make dev` output is interleaved** from both servers. There are no colour prefixes, and
  no process manager was added.
- **Links in the README.** `README.md` links to the uv documentation site. That's a docs
  link, not a runtime asset.
- **Tool versions are unpinned.** Developers need `uv` ≥ 0.10.6 (enforced by
  `tool.uv.required-version`) and Node ≥ 24 (`engine-strict`). The Python toolchain is
  pinned; Node itself isn't pinned to an exact version.

## Manual verification steps

1. Run `make install`, then `make check`. It should end with `37 passed` and `Tests 7 passed (7)`.
2. Run `make dev` and open <http://127.0.0.1:5173>. You should see the "CV Masking" heading.
3. In another terminal:
   - `curl -i http://127.0.0.1:8765/api/health` should return 200 with `{"status":"ok","version":"0.1.0"}`.
   - `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/docs` should print `404`.
   - `lsof -nP -iTCP:8765 -iTCP:5173 -sTCP:LISTEN` should show only `127.0.0.1` addresses.
   - `curl http://$(ipconfig getifaddr en0):8765/api/health` should be refused.
4. Run `CV_MASKING_PORT=80 make dev-backend`. It should fail immediately with `ConfigError`.
5. Press Ctrl-C in the `make dev` terminal. Both servers should stop.

## Questions/decisions for the tech lead

1. **npm install-script policy.** npm 11 now asks for install scripts to be approved. Should
   the repo commit an explicit policy that refuses all install scripts, with `fsevents`
   listed as intentionally not approved? That makes the decision reviewable.
2. **Pre-commit guard.** Should Stage 2, or a small follow-up, add a git pre-commit hook that
   refuses staged document, data or log files? The Stage 0 limitation noted that `synthetic-*`
   fixtures could be misused. It would be a local shell script with no new dependency.
3. **Check on GitHub.** Should `make check` also run in CI if the repo is pushed to GitHub?
   Nothing has been pushed yet.

## Suggested commit message

```
build: stage 1 scaffold with quality gates

Add uv-managed Python 3.12 FastAPI backend with loopback-only entry point,
fixed-host settings, /api/health, and disabled CDN-backed API docs; add
Vite/React/TypeScript static frontend bound to 127.0.0.1; add pytest
(socket-blocked, warnings as errors), ruff, mypy --strict, vitest, eslint,
prettier, and Makefile targets (install, dev, fmt, lint, typecheck, test,
check). No upload or PII logic.
```
