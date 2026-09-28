# Stage 14 handoff — Runtime hardening

## Stage and objective

Stage 14 hardens the localhost API against network and browser abuse: loopback
Host and Origin checks, a process-lifetime session cookie plus CSRF header,
security headers, disabled interactive docs, safe error mapping, request size
and rate limits, metadata-only file logging, and tests that hostile Host/Origin,
missing tokens, path tricks, malformed PDFs, archive bombs, and DTD payloads
fail closed without emitting PII.

Same-origin serving of the built React app remains Stage 15. Development still
uses Vite on `127.0.0.1:5173` proxying `/api` to `127.0.0.1:8765`.

## Architecture decisions

- **ASGI `SecurityGate` is outermost.** It runs before routing. Refusals return
  `{code}` only, with the same security headers as successful responses.
- **Host allowlist.** `127.0.0.1:<settings.port>`, `127.0.0.1:8765` (default),
  and `127.0.0.1:5173` (Vite proxy `changeOrigin`). `localhost` and any other
  name are `SECURITY_HOST_REJECTED` (403). This is the DNS-rebinding control.
- **Origin allowlist.** Matching `http://127.0.0.1:{port,8765,5173}`. A present
  but foreign Origin is refused. Mutating methods without Origin are refused
  (`SECURITY_ORIGIN_REJECTED`). Safe GETs may omit Origin (browser navigations).
- **Unauthenticated routes.** Only `GET /api/health` and `GET /api/session`.
  Health stays token-free for Playwright and `make`. Everything else, including
  GET downloads, needs the session cookie and `X-CSRF-Token`, so a cross-site
  `<img>` or raw `<a href>` cannot pull an output. SameSite=Strict is not enough
  across two `127.0.0.1` ports (same site).
- **Session.** `SessionState.new()` at process start. `GET /api/session` sets
  `cv_masking_session` (HttpOnly, SameSite=Strict, `Secure` off because the app
  is HTTP loopback) and returns `{csrf_token}` in JSON. Compare with
  `hmac.compare_digest`. Tokens live for the process; the cookie `max_age` is
  24 h as a browser hint.
- **Rate limit.** 240 requests / 60 s, one sliding window for the process (one
  HR operator on loopback). Excess is `SECURITY_RATE_LIMITED` (429). Health
  counts toward the window.
- **Size.** `Content-Length` above `HARD_MAX_FILE_BYTES + 1 MiB` (21 MiB) is
  `UPLOAD_FILE_TOO_LARGE` (413) before the body is read. Per-file 20 MB and
  archive/page limits stay in the upload and extractors.
- **Headers.** CSP `default-src 'self'` (script/style/img/font/connect `'self'`,
  `object-src 'none'`, `frame-ancestors 'none'`), `nosniff`, `DENY` framing,
  `no-referrer`, `no-store`, empty camera/mic/geo Permissions-Policy, COOP and
  CORP `same-origin`.
- **Docs stay off.** `docs_url` / `redoc_url` / `openapi_url` remain `None`
  (Stage 1). Unauthenticated `/docs` is 403 (no token); authenticated is 404.
- **Errors.** FastAPI/Starlette `HTTPException` maps to `{code: INTERNAL_ERROR}`
  with the original status. Uncaught exceptions log `type=<ExceptionClass>` only
  and return `INTERNAL_ERROR` 500. `SECURITY_*` codes never become a document
  code.
- **Logging.** `MetadataOnlyFilter` on logger `cv_masking` strips `exc_info` and
  replaces a line that matches `@`, `://`, `/Users/`, `/home/`, `/etc/`,
  `/private/`, or `../` with `log line redacted`. Digit-run redaction was not
  used: UUIDs contain eight-digit runs. `install_metadata_filter` does not raise
  the logger level (that leaked storage UUIDs into unrelated caplog tests).
  `create_runtime_app` writes `data/logs/app.log` (0600, rotate 10 MiB × 7).
- **Frontend.** `openSession()` on mount; every `fetch` and the upload XHR send
  `credentials: "include"` and `X-CSRF-Token`. Downloads are buttons that
  `fetch` a blob; the save name must match
  `filename="redacted-|masked-<uuid>.ext"`. Vite `changeOrigin: true` and
  `allowedHosts: ["127.0.0.1"]`.
- **Tests share a loopback client.** `http_support.app_client` sets
  `base_url=http://127.0.0.1:8765`, opens a session, and sends Origin + CSRF.
  Starlette's default Host `testserver` would fail the Host check.
- **Decompression limits.** Not retuned. PDF xref cap stays 50,000
  (`PDF_RESOURCE_LIMIT`). DOCX archive/XML limits stay at Stage 6b values.
  Stage 14 adds tests that a too-many-pages PDF, zip bomb, DTD/entity payload,
  and traversal archive fail closed without logging payloads.

## Files added/changed

| File | Change |
|---|---|
| `backend/src/cv_masking/api/security.py` | `SessionState`, Host/Origin allowlists, `RateLimiter`, `SecurityGate`, headers |
| `backend/src/cv_masking/api/session.py` | `GET /api/session` cookie + CSRF JSON |
| `backend/src/cv_masking/api/app.py` | Middleware, session router, `HTTPException`/`Exception` handlers, file logging in `create_runtime_app` |
| `backend/src/cv_masking/api/errors.py` | 403/429 for `SECURITY_*`; type-name-only unexpected handler; HTTPException → `INTERNAL_ERROR` |
| `backend/src/cv_masking/logging_setup.py` | Metadata-only filter; rotating `app.log` |
| `backend/src/cv_masking/adapters/local_storage/root.py` | Prepare `logs/` with the other kind directories |
| `backend/src/cv_masking/adapters/local_storage/__init__.py` | Export `LOGS_DIR` |
| `backend/tests/http_support.py` | Loopback authenticated `TestClient` |
| `backend/tests/api/test_security.py` | Hostile Host/Origin, token, CSRF, path, size, rate, cookie flags, malformed PDF, zip bomb/DTD/traversal, log filter |
| `backend/tests/test_logging_setup.py` | Owner-only file, redaction, idempotent filter |
| `backend/tests/test_health.py` | Headers on health; docs 403 then 404 |
| `backend/tests/{api/test_uploads,application/test_worker_process,conftest,storage/test_storage_root}.py` | Authed loopback client; logs directory |
| `backend/pyproject.toml` | pytest `pythonpath` includes `tests` |
| `frontend/src/api.ts` | Session, credentials, CSRF, blob download with safe filename |
| `frontend/src/App.tsx` | Session on mount; download/ZIP are buttons |
| `frontend/src/i18n.ts` | `SECURITY_*` strings and `sessionFailed` |
| `frontend/vite.config.ts` | `changeOrigin`, `allowedHosts` |
| `frontend/tests/App.test.tsx` | Mock `/api/session`; download/export buttons |
| `frontend/tests/vite-config.test.ts` | Proxy and allowed hosts |
| `README.md`, `SECURITY.md`, `THREAT_MODEL.md`, `docs/{data-retention,error-codes,stage-plan,supported-pdf}.md` | Stage 14 status, HTTP 403/429, `data/logs/` |
| `docs/stage-handoffs/stage-14.md` | This file |

No new Python or npm packages. pytest-socket (Stage 1) still disables outbound
sockets in tests.

## Commands run and exact results

- `make check`:
  - file guard: 204 files checked, none refused;
  - `ruff format --check`: 153 files already formatted;
  - `ruff check`: all checks passed;
  - frontend Prettier + ESLint: pass;
  - `mypy --strict`: no issues in 151 source files;
  - `tsc --noEmit`: pass;
  - pytest: **705 passed** in 78.05 s;
  - vitest: 4 files, **11 passed**;
  - Playwright: **2 passed** in 4.0 s (chromium). The e2e webServer started
    the backend on `127.0.0.1:8765`.

## Tests added

- **Hostile Host:** `evil.example` and `localhost:8765` on `/api/health` → 403
  `SECURITY_HOST_REJECTED`; the hostname is absent from the body.
- **Hostile Origin:** POST with `Origin: http://evil.example` → 403
  `SECURITY_ORIGIN_REJECTED`. Mutating request after session but without Origin
  → same code.
- **Missing / wrong token:** no cookie → 403 `SECURITY_TOKEN_INVALID`; wrong
  CSRF → 403; cookie value is not echoed in the body.
- **Path tricks:** `../`, `%2e%2e`, non-uuid, trailing `..` on download stay
  inside `{code}` or health `{status,version}`; no `/etc/` or `root:` in the
  body.
- **Size / rate:** oversized `Content-Length` → 413; monkeypatched limit 3 →
  429 `SECURITY_RATE_LIMITED`.
- **Session cookie:** HttpOnly, SameSite=Strict; CSRF is not in `Set-Cookie`.
- **Malformed PDF upload:** synthetic marker name and phone are absent from the
  400 body and caplog.
- **Page / archive limits:** too-many-pages PDF → `PDF_TOO_MANY_PAGES`; zip bomb
  → `DOCX_RESOURCE_LIMIT`; DTD → `DOCX_MALFORMED`; traversal entry →
  `DOCX_UNSAFE_ARCHIVE`; payloads not logged. DTD upload status/logs omit
  `passwd` / `ENTITY`.
- **Log filter:** email, `/Users/` path, and `exc_info` with a synthetic name
  are redacted; a UUID + state line is kept.
- **File log:** `app.log` mode 0600; UUID kept; email dropped.
- **Health / docs:** CSP, nosniff, no-store on health; `/docs` 403 then 404.
- **Frontend:** session mock; download and ZIP are buttons, not raw links;
  Vite proxy `changeOrigin` and `allowedHosts: ["127.0.0.1"]`.

Existing pytest-socket still fails closed on outbound sockets.

## Security/privacy review

- **Loopback bind unchanged.** Host is still a constant `127.0.0.1`; uvicorn
  still has `proxy_headers=False`. A second LAN device cannot complete a TCP
  handshake to the server.
- **No outbound runtime network.** No new clients, CDNs, or telemetry.
- **No PII in errors or logs.** Induced upload and extractor failures return
  codes only. The filter drops exception text. Tests assert synthetic names,
  phones, emails, and DTD strings are absent.
- **Downloads do not skip CSRF.** Blob `fetch` with credentials and header;
  filename allowlist is uuid-shaped `redacted-` / `masked-` names only.
- **Cookie is HttpOnly.** CSRF is a response JSON field, not in the cookie.
- **`data/logs/`** is under the ignored runtime root (0700 directory, 0600
  file). Agents must not read it.
- **Scope.** No launcher, no bundled static UI, no signed distribution
  (Stage 15).

## Known limitations

- **Dev is two origins.** Vite 5173 and API 8765 are the same site
  (`127.0.0.1`) but different origins. Host/Origin allowlists and CSRF exist
  because of that. Stage 15 serving the UI from the API origin removes the
  proxy exception.
- **Session is process-wide.** Any local browser that can call `/api/session`
  gets a valid cookie for this process. The threat model still assumes a
  single HR user on the laptop (A-2). Stage 15 may add a launcher bootstrap
  token in the first URL.
- **Cookie is not `Secure`.** HTTPS is not used on loopback.
- **Rate limit is global.** One window for the process, not per IP. Fine for
  one operator; a stuck poller shares the budget with uploads.
- **PDF stream size is not a separate cap.** Object count (xref 50,000) is the
  resource proxy; PyMuPDF still decompresses streams internally. The worker
  time budget (Stage 12) is the backstop.
- **Log filter is heuristic.** A value without `@`, `://`, or a listed path
  prefix can still be logged if a caller interpolates it. Call sites must keep
  using ids, codes, and counts.
- **`GET /api/health` has no token.** Intentional for checks. It still requires
  an allowed Host.

## Manual verification steps

1. `make check`
2. `make dev`, open http://127.0.0.1:5173 (synthetic files only)
3. Confirm the page loads, session works (upload/start succeed), and download /
   ZIP save `redacted-<uuid>.<ext>` / `masked-<uuid>.zip`
4. From another terminal on this Mac:
   - `curl -sS -D- http://127.0.0.1:8765/api/batches` → 403
     `SECURITY_TOKEN_INVALID`
   - `curl -sS -H 'Host: evil.example' http://127.0.0.1:8765/api/health` → 403
     `SECURITY_HOST_REJECTED`
5. From a second device on the LAN, a connection to this Mac's LAN IP on 8765
   must fail (nothing is bound there)

Do not use real CVs. Do not open `data/`.

## Questions/decisions for the tech lead

D-41 (Stage 12 queue choices) is already recorded as approved. Question 6 from
Stage 12 (packaging / spawn in the Stage 15 launcher) is still open.

1. **Bootstrap token.** Should Stage 15 replace or wrap this process session
   with a one-time URL token from the `.command` launcher?
2. **PDF stream cap.** Is xref 50,000 enough, or should Stage 15/16 add an
   explicit decompressed-stream budget if PyMuPDF exposes one?
3. **Health authentication.** Keep health public, or require the session after
   the launcher exists?

## Suggested commit message

`feat(security): loopback Host/Origin, session CSRF, headers, rate limits, and metadata-only logs (Stage 14)`
