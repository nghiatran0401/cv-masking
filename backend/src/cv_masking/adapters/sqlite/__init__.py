"""SQLite metadata store (docs/data-retention.md §3-§4)."""

from cv_masking.adapters.sqlite.store import DATABASE_NAME, SqliteMetadataStore

__all__ = ["DATABASE_NAME", "SqliteMetadataStore"]
