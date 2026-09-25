"""Development entry point: ``python -m cv_masking [--reload]``."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import uvicorn

from cv_masking.config import load_settings

APP_FACTORY: Final = "cv_masking.api.app:create_app"
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
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = load_settings()
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
