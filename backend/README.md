# cv-masking backend

FastAPI service for the localhost-only CV masking PoC. It always binds to
`127.0.0.1`; the host is not configurable.

```bash
uv sync --locked                       # install
uv run --locked python -m cv_masking   # run on 127.0.0.1:8765
CV_MASKING_PORT=9000 uv run --locked python -m cv_masking
```

Use the root `Makefile` for lint, type-check, and tests.
