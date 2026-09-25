"""scripts/check-repo-files.sh refuses document, image, and data files in git.

Each test builds a throwaway repository with synthetic bytes only, isolated from
the developer's git configuration.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARD = REPO_ROOT / "scripts" / "check-repo-files.sh"
HOOK = REPO_ROOT / "scripts" / "git-hooks" / "pre-commit"
GIT = shutil.which("git")
MAX_BYTES = 1024 * 1024

PDF = b"%PDF-1.7\n% synthetic\n"
ZIP = b"PK\x03\x04synthetic"
OLE = bytes.fromhex("d0cf11e0a1b11ae1") + b"synthetic"
SQLITE = b"SQLite format 3\x00synthetic"
PNG = b"\x89PNG\r\n\x1a\nsynthetic"
JPEG = b"\xff\xd8\xff\xe0synthetic"
RTF = b"{\\rtf1 synthetic}"
GZIP = b"\x1f\x8bsynthetic"
TEXT = b"synthetic text\n"
# A path that looks like a real CV name; the guard must never print it.
LEAKY_NAME = "CV_Nguyen_Van_Mau_0900000000"


def _run(repo: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    assert GIT is not None
    env = {
        "PATH": f"{Path(GIT).parent}:/usr/bin:/bin",
        "HOME": str(repo),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Synthetic",
        "GIT_AUTHOR_EMAIL": "synthetic@example.test",
        "GIT_COMMITTER_NAME": "Synthetic",
        "GIT_COMMITTER_EMAIL": "synthetic@example.test",
    }
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, temporary repo
        list(argv), cwd=repo, env=env, capture_output=True, text=True, check=False
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert GIT is not None
    return _run(repo, GIT, *args)


def _guard(repo: Path, mode: str = "--staged") -> subprocess.CompletedProcess[str]:
    return _run(repo, str(GUARD), mode)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if GIT is None:
        pytest.fail("git is required for the file guard tests")
    assert _git(tmp_path, "init", "-q", "-b", "main").returncode == 0
    return tmp_path


def _stage(repo: Path, relative: str, data: bytes, *, force: bool = True) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    args = ["add", "-f", "--", relative] if force else ["add", "--", relative]
    assert _git(repo, *args).returncode == 0


def test_scripts_are_executable() -> None:
    for script in (GUARD, HOOK):
        assert script.stat().st_mode & 0o111, script.name


def test_ordinary_source_files_pass(repo: Path) -> None:
    _stage(repo, "src/app.py", b"print('synthetic')\n")
    _stage(repo, "docs/readme.md", TEXT)
    result = _guard(repo)
    assert result.returncode == 0, result.stderr
    assert "2 file(s) checked, none refused" in result.stdout


def test_empty_index_passes(repo: Path) -> None:
    assert _guard(repo).returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        "cv.pdf",
        "cv.PDF",
        "cv.docx",
        "cv.DOCX",
        "cv.doc",
        "cv.rtf",
        "photo.jpg",
        "photo.heic",
        "batch.csv",
        "jobs.sqlite3",
        "report.xlsx",
        "app.log",
        "mail.eml",
        "bundle.zip",
    ],
)
def test_blocked_extensions_are_refused(repo: Path, name: str) -> None:
    _stage(repo, f"docs/{name}", TEXT)
    result = _guard(repo)
    assert result.returncode == 1
    assert "1 with a document, image, data, or log extension" in result.stderr


@pytest.mark.parametrize(
    "data",
    [PDF, ZIP, OLE, SQLITE, PNG, JPEG, RTF, GZIP],
    ids=["pdf", "zip-docx", "ole-doc", "sqlite", "png", "jpeg", "rtf", "gzip"],
)
def test_renamed_documents_are_refused_by_content(repo: Path, data: bytes) -> None:
    _stage(repo, "src/notes.txt", data)
    result = _guard(repo)
    assert result.returncode == 1
    assert "1 whose content is a document, image, archive, or database" in result.stderr


def test_file_without_extension_is_checked_by_content(repo: Path) -> None:
    _stage(repo, "src/README", PDF)
    assert _guard(repo).returncode == 1


@pytest.mark.parametrize(
    "path",
    [
        "data/inputs/0b7e2f4c-1d2a-4c3b-9e8f-7a6b5c4d3e2f",
        "data/notes.md",
        "data/tests/fixtures/synthetic/synthetic-cv.pdf",
    ],
)
def test_anything_in_the_runtime_data_folder_is_refused(repo: Path, path: str) -> None:
    _stage(repo, path, b"synthetic plain text\n")
    result = _guard(repo)
    assert result.returncode == 1
    assert "1 inside the app's runtime data/ folder" in result.stderr


def test_data_folder_rule_is_anchored_at_the_repository_root(repo: Path) -> None:
    _stage(repo, "backend/src/cv_masking/data/schema.py", b"SCHEMA = 1\n")
    assert _guard(repo).returncode == 0


def test_large_files_are_refused(repo: Path) -> None:
    _stage(repo, "src/big.txt", b"a" * (MAX_BYTES + 1))
    _stage(repo, "src/limit.txt", b"a" * MAX_BYTES)
    result = _guard(repo)
    assert result.returncode == 1
    assert "refused 1 of 2" in result.stderr
    assert "1 larger than" in result.stderr


@pytest.mark.parametrize(
    "path",
    [
        "backend/tests/fixtures/synthetic/synthetic-cv.pdf",
        "tests/fixtures/synthetic/docx/synthetic-bilingual.docx",
    ],
)
def test_synthetic_fixtures_are_allowed(repo: Path, path: str) -> None:
    _stage(repo, path, PDF)
    result = _guard(repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "path",
    [
        "backend/tests/fixtures/synthetic/cv.pdf",
        "backend/tests/fixtures/synthetic-cv.pdf",
        "backend/tests/fixtures/other/synthetic-cv.pdf",
        "backend/synthetic/synthetic-cv.pdf",
        "backend/xtests/fixtures/synthetic/synthetic-cv.pdf",
    ],
)
def test_fixture_exception_is_narrow(repo: Path, path: str) -> None:
    _stage(repo, path, PDF)
    assert _guard(repo).returncode == 1


def test_synthetic_fixtures_still_have_a_size_limit(repo: Path) -> None:
    _stage(repo, "tests/fixtures/synthetic/synthetic-big.pdf", PDF + b"a" * MAX_BYTES)
    assert _guard(repo).returncode == 1


def test_index_content_is_checked_not_the_working_tree(repo: Path) -> None:
    _stage(repo, "src/notes.txt", PDF)
    (repo / "src" / "notes.txt").write_bytes(TEXT)
    assert _guard(repo).returncode == 1


def test_staged_mode_ignores_committed_files_but_all_mode_does_not(repo: Path) -> None:
    _stage(repo, "legacy.pdf", PDF)
    assert _git(repo, "commit", "-q", "--no-verify", "-m", "synthetic").returncode == 0
    _stage(repo, "src/app.py", TEXT)
    assert _guard(repo, "--staged").returncode == 0
    assert _guard(repo, "--all").returncode == 1


def test_output_never_contains_file_names(repo: Path) -> None:
    _stage(repo, f"inbox/{LEAKY_NAME}.pdf", PDF)
    _stage(repo, f"inbox/{LEAKY_NAME}.txt", PDF)
    result = _guard(repo)
    assert result.returncode == 1
    assert "refused 2 of 2" in result.stderr
    for fragment in ("Nguyen", "0900000000", "inbox"):
        assert fragment not in result.stdout + result.stderr


def test_unusual_file_names_are_handled(repo: Path) -> None:
    _stage(repo, "docs/a file\twith\nodd name.pdf", TEXT)
    _stage(repo, "docs/tiếng việt.md", TEXT)
    result = _guard(repo)
    assert result.returncode == 1
    assert "refused 1 of 2" in result.stderr


def test_bad_mode_is_a_usage_error(repo: Path) -> None:
    assert _guard(repo, "--everything").returncode == 2


def test_pre_commit_hook_blocks_the_commit(repo: Path) -> None:
    hooks = repo / "scripts" / "git-hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(GUARD, repo / "scripts" / "check-repo-files.sh")
    shutil.copy2(HOOK, hooks / "pre-commit")
    assert _git(repo, "config", "core.hooksPath", "scripts/git-hooks").returncode == 0
    _stage(repo, "scripts/check-repo-files.sh", GUARD.read_bytes())
    _stage(repo, "scripts/git-hooks/pre-commit", HOOK.read_bytes())
    _stage(repo, "cv.pdf", PDF)

    blocked = _git(repo, "commit", "-q", "-m", "synthetic")
    assert blocked.returncode == 1
    assert "cv-masking file guard: refused 1 of 3" in blocked.stderr
    assert _git(repo, "rev-parse", "--verify", "-q", "HEAD").returncode != 0

    assert _git(repo, "rm", "-q", "--cached", "cv.pdf").returncode == 0
    allowed = _git(repo, "commit", "-q", "-m", "synthetic")
    assert allowed.returncode == 0, allowed.stderr
