"""Outbound fetch of one allowlisted CV URL. The adapter is the only implementation."""

from typing import Protocol


class CvSourceError(Exception):
    """The file host did not return a body. The message is static and has no URL."""

    def __init__(self) -> None:
        super().__init__("source fetch failed")


class CvSource(Protocol):
    """A CV fetch. Tests pass a fake; production uses the HTTPS adapter."""

    def fetch(self, href: str, *, max_bytes: int) -> bytes: ...
