"""npm must never run dependency install scripts (THREAT_MODEL.md T-16)."""

import json
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
LIFECYCLE_SCRIPTS = {"preinstall", "install", "postinstall", "prepare", "prepublish"}


def test_npmrc_refuses_install_scripts() -> None:
    lines = (FRONTEND / ".npmrc").read_text(encoding="utf-8").splitlines()
    assert "ignore-scripts=true" in lines


def test_frontend_package_has_no_lifecycle_scripts() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    scripts = set(package.get("scripts", {}))
    assert not scripts & LIFECYCLE_SCRIPTS
    hooks = {f"{prefix}{name}" for name in scripts for prefix in ("pre", "post")}
    assert not scripts & hooks
