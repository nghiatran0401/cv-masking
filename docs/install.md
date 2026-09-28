# Install, run, and uninstall (macOS)

Status: Stage 15. This is an **unsigned** proof of concept (D-39). It is not
notarized. Bank legal has not confirmed the PyMuPDF AGPL-3.0 licence path;
do not treat this as an IT-approved distribution until that happens.

Tested on **Apple Silicon** (this checkout: arm64, Apple M2). **Intel
(x86_64) is not tested.** Install on the HR Mac itself; do not copy
`backend/.venv` between architectures.

## What HR runs

1. Quit any `make dev` session on port 8765.
2. Double-click `scripts/cv-masking.command`.
3. The first time, macOS Gatekeeper may block an unsigned app: Finder →
   right-click the `.command` file → Open → Open.
4. Terminal stays open while the app runs. Closing that window or pressing
   Ctrl+C stops the server. The worker gets up to 10 seconds, then in-flight
   work becomes `JOB_INTERRUPTED`. Inputs, outputs, and metadata in `data/`
   are kept (D-24).
5. The default browser opens `http://127.0.0.1:8765/?bootstrap=…`. The token
   is one-time; the page removes it from the address bar after the session
   cookie is set.

A second double-click does not start another server. If the app is already
healthy it only opens the browser on `http://127.0.0.1:8765/` (the existing
session cookie is enough).

HR does **not** need Node.js at runtime.

## What IT installs (this laptop / a prebuilt tree)

On the target Mac, with network only for the one-time dependency fetch:

```bash
# Tools: uv ≥ 0.10.6, Node.js ≥ 24 (build machine only), GNU Make
uv python install 3.12
make install
make build
```

`make build` writes the React app into `backend/src/cv_masking/static/`
(gitignored). After that, Node is unused.

Runtime is the uv virtualenv at `backend/.venv` (normal CPython, not a
frozen binary) so the Stage 12 worker `spawn` keeps the same interpreter.

Optional: exclude Time Machine for the data folder:

```bash
tmutil addexclusion "$(pwd)/data"
```

## Development (engineers)

```bash
make dev          # API 127.0.0.1:8765 + Vite 127.0.0.1:5173 (no bootstrap token)
make check        # includes make build
```

`make dev` does not take the desktop lock and does not require a UI build.
Quit it before using the `.command` launcher.

## Uninstall

1. Quit the app (close the Terminal window that is running the `.command`, or
   Ctrl+C).
2. Delete the project folder. That removes the program, `.venv`, and `data/`
   (inputs, outputs, metadata, logs, lock). Deletion is not forensic erasure;
   FileVault is the assumption (A-1).
3. Masked files already saved to Downloads are outside the app; delete those
   separately if required.
4. Time Machine: if `data/` was backed up before `tmutil addexclusion`, old
   copies may remain on the backup disk.

There is no other install location, LaunchAgent, or application support
folder in this PoC.
