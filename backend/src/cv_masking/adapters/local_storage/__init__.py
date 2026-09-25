"""Local filesystem storage under the per-user cache root (docs/data-retention.md §3)."""

from cv_masking.adapters.local_storage.root import CacheRoot, StoreKind, default_cache_root
from cv_masking.adapters.local_storage.stores import LocalInputStore, LocalOutputStore
from cv_masking.adapters.local_storage.sweeper import LocalStorageSweeper
from cv_masking.adapters.local_storage.work_area import LocalWorkArea

__all__ = [
    "CacheRoot",
    "LocalInputStore",
    "LocalOutputStore",
    "LocalStorageSweeper",
    "LocalWorkArea",
    "StoreKind",
    "default_cache_root",
]
