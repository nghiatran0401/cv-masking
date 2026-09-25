"""Local filesystem storage under the per-user storage root (docs/data-retention.md §3)."""

from cv_masking.adapters.local_storage.root import (
    METADATA_DIR,
    StorageRoot,
    StoreKind,
    default_storage_root,
)
from cv_masking.adapters.local_storage.stores import LocalInputStore, LocalOutputStore
from cv_masking.adapters.local_storage.sweeper import LocalStorageSweeper
from cv_masking.adapters.local_storage.work_area import LocalWorkArea

__all__ = [
    "METADATA_DIR",
    "LocalInputStore",
    "LocalOutputStore",
    "LocalStorageSweeper",
    "LocalWorkArea",
    "StorageRoot",
    "StoreKind",
    "default_storage_root",
]
