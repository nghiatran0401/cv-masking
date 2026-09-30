# cv-masking backend

FastAPI service for the localhost-only CV masking PoC. It always binds to
`127.0.0.1`; the host is not configurable.

From the repository root on macOS, `make install` creates `backend/.venv` for
this project only, using a uv-managed Python 3.12. It does not use the system
Python. On Windows, run `scripts\setup-windows.ps1` once; that creates
`backend\.venv\Scripts\python.exe` and does not use GNU Make.

```bash
make -C .. install                     # create backend/.venv and install locked deps
uv run --locked python -m cv_masking   # run on 127.0.0.1:8765
CV_MASKING_PORT=9000 uv run --locked python -m cv_masking
```

Use the root `Makefile` for lint, type-check, and tests.
