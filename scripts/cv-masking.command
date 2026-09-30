#!/bin/bash
# Unsigned macOS launcher for the CV Masking PoC (D-39). Double-click in Finder.
# Gatekeeper: first run may need right-click → Open. Not notarized.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/backend/.venv/bin/python"
UI="$ROOT/backend/src/cv_masking/static/index.html"
if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment missing. In Terminal: cd \"$ROOT\" && make setup" >&2
  exit 1
fi
if [[ ! -f "$UI" ]]; then
  echo "UI build missing. In Terminal: cd \"$ROOT\" && make build" >&2
  exit 1
fi
cd "$ROOT"
exec "$PYTHON" -m cv_masking --desktop
