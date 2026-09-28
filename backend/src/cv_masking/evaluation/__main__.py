"""``python -m cv_masking.evaluation`` — metadata-only synthetic (or authorized) report."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from cv_masking.evaluation.harness import run_authorized, run_synthetic
from cv_masking.evaluation.report import report_json, report_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cv_masking.evaluation",
        description="Compute metadata-only evaluation metrics. Never prints document values.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="write Markdown instead of JSON",
    )
    parser.add_argument(
        "--authorized",
        type=Path,
        help="HR-only: directory of authorized CVs (requires CV_MASKING_AUTHORIZED_EVAL=1)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    report = run_authorized(args.authorized) if args.authorized is not None else run_synthetic()
    text = report_markdown(report) if args.markdown else report_json(report)
    print(text, end="")


if __name__ == "__main__":
    main()
