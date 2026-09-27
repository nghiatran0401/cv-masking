"""Run pytest after loading PyMuPDF.

PyMuPDF 1.28's native module segfaults if it is first imported after pytest
has started (including from assertion-rewritten test modules). It also
segfaults in C++ destructors when the process exits. Load it first, then
leave via os._exit so those destructors do not run.
"""

import os
import sys

import pymupdf
import pytest

_ = pymupdf.VersionBind


def main() -> None:
    code = pytest.main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
