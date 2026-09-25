#!/bin/bash
# Refuse documents, images, archives, databases, spreadsheets, logs, and large files
# in git (SECURITY.md §3). Checks the content in the git index, so renamed or
# force-added files are caught. The only exception is a file named synthetic-*
# inside a tests/fixtures/synthetic/ directory.
#
#   --staged  files added, copied, modified, or renamed in the index (pre-commit hook)
#   --all     every tracked file (make check)
#
# File paths are never printed: a real CV's file name often contains the
# candidate's name. Run `git diff --cached --name-only` locally to find them.

set -euo pipefail

readonly MAX_BYTES=1048576
readonly BLOCKED_EXTENSIONS=" pdf doc docx docm dot dotx dotm odt ods rtf pages numbers key \
png jpg jpeg gif bmp tif tiff heic webp zip 7z rar tar gz tgz \
sqlite sqlite3 db csv tsv xls xlsx xlsm eml msg log dump "

mode="${1:-}"
case "$mode" in
--staged) list_cmd=(git diff --cached --name-only --diff-filter=ACMR -z) ;;
--all) list_cmd=(git ls-files -z) ;;
*)
    echo "usage: $0 --staged | --all" >&2
    exit 2
    ;;
esac

is_synthetic_fixture() {
    case "/$1" in
    */tests/fixtures/synthetic/*) ;;
    *) return 1 ;;
    esac
    case "${1##*/}" in
    synthetic-*) return 0 ;;
    *) return 1 ;;
    esac
}

blocked_extension() {
    local name="${1##*/}" ext
    case "$name" in
    *.*) ext="$(printf '%s' "${name##*.}" | tr '[:upper:]' '[:lower:]')" ;;
    *) return 1 ;;
    esac
    case "$BLOCKED_EXTENSIONS" in
    *" $ext "*) return 0 ;;
    *) return 1 ;;
    esac
}

# First bytes of the indexed blob, as lowercase hex.
signature() {
    git cat-file blob ":$1" | head -c 16 | od -An -tx1 | tr -d ' \n'
}

blocked_signature() {
    case "$(signature "$1")" in
    25504446*) return 0 ;;          # %PDF
    504b0304* | 504b0506*) return 0 ;; # ZIP (DOCX, XLSX, ODT, ...)
    d0cf11e0a1b11ae1*) return 0 ;;  # OLE (DOC, XLS, MSG, encrypted DOCX)
    7b5c727466*) return 0 ;;        # {\rtf
    53514c69746520666f726d6174203300*) return 0 ;; # SQLite format 3
    89504e47*) return 0 ;;          # PNG
    ffd8ff*) return 0 ;;            # JPEG
    47494638*) return 0 ;;          # GIF8
    1f8b*) return 0 ;;              # gzip
    377abcaf271c*) return 0 ;;      # 7z
    526172211a07*) return 0 ;;      # RAR
    *) return 1 ;;
    esac
}

too_large() {
    [ "$(git cat-file -s ":$1")" -gt "$MAX_BYTES" ]
}

checked=0
by_extension=0
by_content=0
by_size=0
while IFS= read -r -d '' path; do
    # Deleted-in-worktree files are still in the index; symlinks and submodules have no blob to read.
    [ "$(git cat-file -t ":$path" 2>/dev/null || true)" = "blob" ] || continue
    checked=$((checked + 1))
    if too_large "$path"; then
        by_size=$((by_size + 1))
        continue
    fi
    is_synthetic_fixture "$path" && continue
    if blocked_extension "$path"; then
        by_extension=$((by_extension + 1))
    elif blocked_signature "$path"; then
        by_content=$((by_content + 1))
    fi
done < <("${list_cmd[@]}")

refused=$((by_extension + by_content + by_size))
if [ "$refused" -gt 0 ]; then
    {
        echo "cv-masking file guard: refused $refused of $checked file(s)."
        [ "$by_extension" -eq 0 ] || echo "  $by_extension with a document, image, data, or log extension"
        [ "$by_content" -eq 0 ] || echo "  $by_content whose content is a document, image, archive, or database"
        [ "$by_size" -eq 0 ] || echo "  $by_size larger than $MAX_BYTES bytes"
        echo "Only synthetic fixtures may be committed: tests/fixtures/synthetic/**/synthetic-*"
        echo "List staged files locally with: git diff --cached --name-only"
        echo "Do not paste real file names or contents into chat tools."
    } >&2
    exit 1
fi
echo "cv-masking file guard: $checked file(s) checked, none refused."
