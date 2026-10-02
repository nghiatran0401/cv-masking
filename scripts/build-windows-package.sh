#!/bin/bash
# Build a ready-to-run Windows package on macOS: dist/cv-masking-windows-<version>.zip
#
# The zip holds a private CPython 3.12 for Windows, the locked runtime libraries
# (Windows wheels, hash-checked), the backend source, and the built UI. The HR
# laptop needs no Python, uv, Node, or internet. Python comes from uv's managed
# downloads (python-build-standalone), which uv checks against its own checksums.
#
# Layout inside the zip keeps backend/src/cv_masking/... so the app's storage root
# resolves to CVMasking\data next to the code, as it does in the repository.

set -euo pipefail

readonly PYTHON_KEY="cpython-3.12.14-windows-x86_64-none"
readonly WHEEL_PLATFORM="x86_64-pc-windows-msvc"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ROOT
readonly WORK="$ROOT/build/windows"
readonly STAGE="$WORK/CVMasking"
readonly TEMPLATES="$ROOT/scripts/windows-package"
readonly DIST="$ROOT/dist"

for tool in uv npm zip perl shasum; do
    command -v "$tool" >/dev/null || {
        echo "$tool is not installed." >&2
        exit 1
    }
done

version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$ROOT/backend/pyproject.toml" | head -n 1)"
revision="$(git -C "$ROOT" rev-parse --short HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain -- backend frontend scripts)" ]; then
    revision="$revision-dirty"
fi
readonly name="cv-masking-windows-$version-$revision"

echo "==> Building the UI"
make -C "$ROOT" build

echo "==> Preparing $STAGE"
rm -rf "$WORK"
mkdir -p "$STAGE/backend/src" "$DIST"

echo "==> Fetching $PYTHON_KEY"
UV_PYTHON_INSTALL_DIR="$WORK/python-download" uv python install --no-bin "$PYTHON_KEY"
cp -R "$WORK/python-download/$PYTHON_KEY" "$STAGE/python"
readonly SITE="$STAGE/python/Lib/site-packages"

echo "==> Installing locked Windows wheels"
uv export --project "$ROOT/backend" --frozen --no-dev --no-emit-project \
    --format requirements-txt --quiet -o "$WORK/requirements.txt"
uv pip install \
    --target "$SITE" \
    --python-platform "$WHEEL_PLATFORM" \
    --python-version 3.12 \
    --only-binary :all: \
    --require-hashes \
    --no-deps \
    -r "$WORK/requirements.txt"
# Console entry points (fastapi.exe, uvicorn.exe, ...) are not used by the launcher.
rm -rf "$SITE/bin"

echo "==> Copying the app"
cp -R "$ROOT/backend/src/cv_masking" "$STAGE/backend/src/cv_masking"
find "$STAGE/backend" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$STAGE" -name ".DS_Store" -delete
# A .pth path is relative to site-packages: python\Lib\site-packages -> CVMasking.
printf '..\\..\\..\\backend\\src\r\n' >"$SITE/cv-masking.pth"

crlf() { perl -pe 's/\r?\n/\r\n/' "$1" >"$2"; }
crlf "$TEMPLATES/start.bat" "$STAGE/Start CV Masking.bat"
crlf "$TEMPLATES/install.bat" "$STAGE/Install CV Masking.bat"
crlf "$TEMPLATES/HUONG-DAN.txt" "$STAGE/HUONG-DAN.txt"

echo "==> Verifying the package"
fail() {
    echo "package check failed: $1" >&2
    exit 1
}
[ -f "$STAGE/python/python.exe" ] || fail "python.exe missing"
[ -f "$STAGE/backend/src/cv_masking/static/index.html" ] || fail "UI build missing"
[ -f "$SITE/pymupdf/_mupdf.pyd" ] || fail "PyMuPDF is not the Windows build"
[ -d "$SITE/fastapi" ] && [ -d "$SITE/presidio_analyzer" ] || fail "runtime libraries missing"
[ ! -e "$STAGE/data" ] || fail "a data folder must never be packaged"
documents="$(find "$STAGE" -type f \( -iname '*.pdf' -o -iname '*.doc' -o -iname '*.docx' \
    -o -iname '*.sqlite*' -o -iname '*.db' -o -iname '*.log' \) | wc -l | tr -d ' ')"
[ "$documents" -eq 0 ] || fail "$documents document, database, or log file(s) in the package"
# Same relative layout as Windows: the storage root and UI resolve inside CVMasking.
uv run --project "$ROOT/backend" --locked python - "$STAGE" <<'PY'
import sys
from pathlib import Path

stage = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(stage / "backend" / "src"))

from cv_masking.adapters.local_storage import default_storage_root
from cv_masking.api.ui import resolve_static_directory

assert default_storage_root() == stage / "data", "storage root is outside the package"
static = resolve_static_directory({})
assert static is not None and static.is_relative_to(stage), "UI resolves outside the package"
PY

echo "==> Zipping"
rm -f "$DIST/$name.zip" "$DIST/$name.zip.sha256"
(cd "$WORK" && zip -qr -X "$DIST/$name.zip" CVMasking)
(cd "$DIST" && shasum -a 256 "$name.zip" >"$name.zip.sha256")
rm -rf "$WORK"

echo "Package: dist/$name.zip ($(du -h "$DIST/$name.zip" | cut -f1))"
echo "SHA-256: dist/$name.zip.sha256"
