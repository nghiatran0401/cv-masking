import math
import re
from datetime import datetime, timedelta
from typing import Final

from cv_masking.domain.errors import InvariantError

_IDENTIFIER_RE: Final = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_SEMVER_RE: Final = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def require_utc(value: object, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise InvariantError(f"{field} must be a timezone-aware UTC datetime")


def require_int(value: object, field: str, *, minimum: int, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvariantError(f"{field} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise InvariantError(f"{field} is out of range")


def require_finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvariantError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise InvariantError(f"{field} must be finite")
    return number


def require_bool(value: object, field: str) -> None:
    if not isinstance(value, bool):
        raise InvariantError(f"{field} must be a boolean")


def require_identifier(value: object, field: str) -> None:
    """Lowercase ASCII identifier: rules out names, emails, and other free text."""
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise InvariantError(f"{field} must be a lowercase ASCII identifier")


def require_semver(value: object, field: str) -> None:
    if not isinstance(value, str) or _SEMVER_RE.fullmatch(value) is None:
        raise InvariantError(f"{field} must be a MAJOR.MINOR.PATCH version")
