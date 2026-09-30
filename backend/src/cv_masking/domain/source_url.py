"""Allowlisted company-file-host CV URLs (D-50).

The hostname is a bare string so it can stay identical to the frontend constant
without embedding a scheme in source that the page would be allowed to call.
"""

from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, urlsplit

SOURCE_CV_HOST: Final = "data.ehiring.ehr.vib"
MAX_SOURCE_URL_LENGTH: Final = 2048
MAX_CV_FILENAME_LENGTH: Final = 200
_UNSAFE_NAME: Final = frozenset('<>:"|?*\\/')


@dataclass(frozen=True, slots=True)
class CvSourceUrl:
    """A canonical https URL and the filename used only to detect a spoofed type."""

    href: str
    filename: str


def parse_cv_source_url(raw: str) -> CvSourceUrl | None:
    """Return a canonical allowlisted PDF or DOCX URL, or None when it is refused.

    The raw value is not logged. A refused URL is indistinguishable from any other
    malformed upload once the caller maps None to ``UPLOAD_MALFORMED_REQUEST``.
    """
    href = _canonical_href(raw)
    if href is None:
        return None
    filename = _filename(urlsplit(href).path)
    if filename is None:
        return None
    return CvSourceUrl(href=href, filename=filename)


def _canonical_href(raw: str) -> str | None:
    if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_SOURCE_URL_LENGTH:
        return None
    if any(char.isspace() or ord(char) < 32 or char == "\\" for char in raw):
        return None
    parts = urlsplit(raw)
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or parts.hostname != SOURCE_CV_HOST
        or parts.port not in (None, 443)
        or parts.fragment != ""
    ):
        return None
    path = parts.path
    if not path.startswith("/") or any(segment == "" for segment in path.split("/")[1:]):
        return None
    decoded_segments = [unquote(segment) for segment in path.split("/")[1:]]
    if any(
        segment in {".", ".."} or "\\" in segment or "/" in segment for segment in decoded_segments
    ):
        return None
    query = f"?{parts.query}" if parts.query else ""
    return f"https://{SOURCE_CV_HOST}{path}{query}"


def _filename(path: str) -> str | None:
    segment = unquote(path.rsplit("/", 1)[-1])
    if (
        not segment
        or len(segment) > MAX_CV_FILENAME_LENGTH
        or segment.startswith(".")
        or any(ord(char) < 32 or char in _UNSAFE_NAME for char in segment)
    ):
        return None
    lower = segment.lower()
    if lower.endswith(".pdf"):
        extension = ".pdf"
    elif lower.endswith(".docx"):
        extension = ".docx"
    else:
        return None
    stem = segment[: -len(extension)]
    if stem == "" or stem.endswith("."):
        return None
    return f"{stem}{extension}"
