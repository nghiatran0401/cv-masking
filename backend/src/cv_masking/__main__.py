"""Loopback entry point: ``python -m cv_masking [--reload | --desktop]``."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import uvicorn

from cv_masking.config import load_settings
from cv_masking.desktop import run_desktop

APP_FACTORY: Final = "cv_masking.api.app:create_runtime_app"
PACKAGE_DIR: Final = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cv_masking",
        description="Run the CV masking API on 127.0.0.1.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="restart on source changes (development only)",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="single-instance UI: lock, bootstrap token, open the default browser",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="with --desktop, wait for health but do not open a browser",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.desktop and args.reload:
        raise SystemExit("use --desktop or --reload, not both")
    settings = load_settings()
    if args.desktop:
        run_desktop(open_browser=not args.no_browser, settings=settings)
        return
    uvicorn.run(
        APP_FACTORY,
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        reload_dirs=[str(PACKAGE_DIR)] if args.reload else None,
        proxy_headers=False,
        server_header=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
