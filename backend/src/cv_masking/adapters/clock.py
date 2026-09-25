from datetime import UTC, datetime


class SystemClock:
    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(UTC)
