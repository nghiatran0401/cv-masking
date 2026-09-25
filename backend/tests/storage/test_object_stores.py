import errno
import hashlib
import inspect
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from cv_masking.adapters.local_storage import CacheRoot, LocalInputStore, LocalOutputStore
from cv_masking.adapters.local_storage import stores as stores_module
from cv_masking.adapters.local_storage.root import OBJECT_NAME_RE
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import ObjectRef, Sha256Digest
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.storage import ObjectSink, StorageError, StoredObject

PDF = DocumentFormat.PDF
DOCX = DocumentFormat.DOCX
DATA = b"%PDF-1.7\n% synthetic test object\n" * 10
type Store = LocalInputStore | LocalOutputStore
STORES: dict[str, type[LocalInputStore] | type[LocalOutputStore]] = {
    "inputs": LocalInputStore,
    "outputs": LocalOutputStore,
}
LIMIT_CODES = {"inputs": ErrorCode.UPLOAD_FILE_TOO_LARGE, "outputs": ErrorCode.STORAGE_WRITE_FAILED}


@pytest.fixture(params=list(STORES))
def kind(request: pytest.FixtureRequest) -> str:
    value: str = request.param
    return value


@pytest.fixture
def store(root: CacheRoot, kind: str) -> Store:
    return STORES[kind](root)


def _writer(*chunks: bytes) -> Callable[[ObjectSink], None]:
    def produce(sink: ObjectSink) -> None:
        for chunk in chunks:
            sink.write(chunk)

    return produce


def _entries(root: CacheRoot, kind: str) -> list[str]:
    return sorted(path.name for path in (root.path / kind).iterdir())


def _code(error: pytest.ExceptionInfo[StorageError]) -> ErrorCode:
    return error.value.code


def _save(store: Store, data: bytes = DATA, fmt: DocumentFormat = PDF) -> StoredObject:
    return store.save(fmt, _writer(data), max_bytes=HARD_MAX_FILE_BYTES)


def _planted(root: CacheRoot, kind: str, fmt: DocumentFormat = PDF) -> tuple[ObjectRef, Path]:
    ref = ObjectRef(uuid4())
    suffix = ".pdf" if fmt is PDF else ".docx"
    return ref, root.path / kind / f"{ref.value}{suffix}"


# ------------------------------------------------------------------ save


@pytest.mark.parametrize("fmt", [PDF, DOCX])
def test_save_round_trips_with_hash_and_size(
    store: Store, root: CacheRoot, kind: str, fmt: DocumentFormat
) -> None:
    stored = _save(store, DATA, fmt)
    assert stored.document_format is fmt
    assert stored.size_bytes == len(DATA)
    assert stored.sha256 == Sha256Digest(hashlib.sha256(DATA).hexdigest())
    (name,) = _entries(root, kind)
    assert OBJECT_NAME_RE.fullmatch(name)
    assert name == f"{stored.ref.value}{'.pdf' if fmt is PDF else '.docx'}"
    assert stat.S_IMODE((root.path / kind / name).stat().st_mode) == 0o400
    with store.open(stored.ref, fmt) as file:
        assert file.read() == DATA
    store.verify(stored)


def test_each_save_gets_a_new_random_ref(store: Store) -> None:
    refs = {_save(store).ref for _ in range(5)}
    assert len(refs) == 5
    assert all(ref.value.version == 4 for ref in refs)


def test_input_store_saves_a_chunk_stream(input_store: LocalInputStore) -> None:
    chunks = [DATA[i : i + 7] for i in range(0, len(DATA), 7)]
    stored = input_store.save_stream(PDF, iter(chunks), max_bytes=len(DATA))
    assert stored.size_bytes == len(DATA)
    input_store.verify(stored)


def test_size_limit_is_exact(store: Store, root: CacheRoot, kind: str) -> None:
    assert store.save(PDF, _writer(DATA), max_bytes=len(DATA)).size_bytes == len(DATA)
    with pytest.raises(StorageError) as caught:
        store.save(PDF, _writer(DATA, b"x"), max_bytes=len(DATA))
    assert _code(caught) is LIMIT_CODES[kind]
    assert len(_entries(root, kind)) == 1


@pytest.mark.parametrize("max_bytes", [0, -1, HARD_MAX_FILE_BYTES + 1, True, 1.5])
def test_invalid_size_limits_are_refused(store: Store, max_bytes: object) -> None:
    with pytest.raises(StorageError):
        store.save(PDF, _writer(DATA), max_bytes=max_bytes)  # type: ignore[arg-type]


def test_empty_object_is_refused(store: Store, root: CacheRoot, kind: str) -> None:
    with pytest.raises(StorageError) as caught:
        store.save(PDF, _writer(), max_bytes=100)
    assert _code(caught) is ErrorCode.STORAGE_WRITE_FAILED
    assert _entries(root, kind) == []


def test_failing_producer_leaves_nothing_behind(store: Store, root: CacheRoot, kind: str) -> None:
    def produce(sink: ObjectSink) -> None:
        sink.write(DATA)
        raise ValueError("synthetic producer failure")

    with pytest.raises(ValueError, match="synthetic producer failure"):
        store.save(PDF, produce, max_bytes=HARD_MAX_FILE_BYTES)
    assert _entries(root, kind) == []


def test_interrupted_stream_leaves_nothing_behind(
    input_store: LocalInputStore, root: CacheRoot
) -> None:
    def chunks() -> Iterator[bytes]:
        yield DATA
        raise ConnectionResetError("synthetic client disconnect")

    with pytest.raises(StorageError) as caught:
        input_store.save_stream(PDF, chunks(), max_bytes=HARD_MAX_FILE_BYTES)
    assert _code(caught) is ErrorCode.STORAGE_WRITE_FAILED
    assert _entries(root, "inputs") == []


def test_non_bytes_writes_are_refused(store: Store, root: CacheRoot, kind: str) -> None:
    with pytest.raises(TypeError):
        store.save(PDF, lambda sink: sink.write("text"), max_bytes=100)  # type: ignore[arg-type]
    assert _entries(root, kind) == []


def test_disk_full_while_writing_leaves_nothing_behind(
    store: Store, root: CacheRoot, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(fd: int) -> None:
        raise OSError(errno.ENOSPC, "synthetic disk full")

    monkeypatch.setattr("cv_masking.adapters.local_storage.stores.os.fsync", fail)
    with pytest.raises(StorageError) as caught:
        _save(store)
    assert _code(caught) is ErrorCode.STORAGE_WRITE_FAILED
    assert _entries(root, kind) == []


def test_failure_after_linking_removes_the_final_object(
    store: Store, root: CacheRoot, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync
    calls: list[int] = []

    def fail_on_directory_sync(fd: int) -> None:
        calls.append(fd)
        if len(calls) == 2:
            raise OSError(errno.EIO, "synthetic directory sync failure")
        real_fsync(fd)

    monkeypatch.setattr("cv_masking.adapters.local_storage.stores.os.fsync", fail_on_directory_sync)
    with pytest.raises(StorageError):
        _save(store)
    assert _entries(root, kind) == []


def test_save_never_overwrites_an_existing_object(
    store: Store, root: CacheRoot, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = UUID("12345678-1234-4234-8234-123456789abc")
    temp = UUID("abcdefab-cdef-4abc-8def-abcdefabcdef")
    values = iter([fixed, temp])
    monkeypatch.setattr(stores_module, "uuid4", lambda: next(values))
    existing = root.path / kind / f"{fixed}.pdf"
    existing.write_bytes(b"synthetic existing object")
    with pytest.raises(StorageError) as caught:
        _save(store)
    assert _code(caught) is ErrorCode.STORAGE_WRITE_FAILED
    assert existing.read_bytes() == b"synthetic existing object"
    assert _entries(root, kind) == [existing.name]


# ------------------------------------------------------------------ open and verify


def test_missing_object_fails_integrity(store: Store) -> None:
    with pytest.raises(StorageError) as caught:
        store.open(ObjectRef(uuid4()), PDF)
    assert _code(caught) is ErrorCode.STORAGE_INTEGRITY_FAILED


def test_symlink_at_object_name_is_refused(
    store: Store, root: CacheRoot, kind: str, outside: Path
) -> None:
    ref, path = _planted(root, kind)
    path.symlink_to(outside / "keep.txt")
    with pytest.raises(StorageError) as caught:
        store.open(ref, PDF)
    assert _code(caught) is ErrorCode.STORAGE_PATH_REJECTED


def test_hard_link_at_object_name_is_refused(
    store: Store, root: CacheRoot, kind: str, outside: Path
) -> None:
    ref, path = _planted(root, kind)
    (outside / "keep.txt").chmod(0o600)
    os.link(outside / "keep.txt", path)
    with pytest.raises(StorageError) as caught:
        store.open(ref, PDF)
    assert _code(caught) is ErrorCode.STORAGE_PATH_REJECTED


def test_fifo_at_object_name_is_refused_without_blocking(
    store: Store, root: CacheRoot, kind: str
) -> None:
    ref, path = _planted(root, kind)
    os.mkfifo(path, 0o600)
    with pytest.raises(StorageError) as caught:
        store.open(ref, PDF)
    assert _code(caught) is ErrorCode.STORAGE_PATH_REJECTED


def test_directory_at_object_name_is_refused(store: Store, root: CacheRoot, kind: str) -> None:
    ref, path = _planted(root, kind)
    path.mkdir(mode=0o700)
    with pytest.raises(StorageError) as caught:
        store.open(ref, PDF)
    assert _code(caught) is ErrorCode.STORAGE_PATH_REJECTED
    with pytest.raises(StorageError):
        store.delete(ref, PDF)
    assert path.is_dir()


def test_world_readable_object_is_refused(store: Store, root: CacheRoot, kind: str) -> None:
    ref, path = _planted(root, kind)
    path.write_bytes(DATA)
    path.chmod(0o644)
    with pytest.raises(StorageError) as caught:
        store.open(ref, PDF)
    assert _code(caught) is ErrorCode.STORAGE_PATH_REJECTED


@pytest.mark.parametrize(
    ("ref", "fmt"),
    [
        (uuid4(), PDF),
        ("../../etc/passwd", PDF),
        (ObjectRef(uuid4()), "pdf"),
        (ObjectRef(uuid4()), "../x"),
    ],
    ids=["raw-uuid", "traversal-string", "string-format", "traversal-format"],
)
def test_untyped_refs_and_formats_are_refused(store: Store, ref: object, fmt: object) -> None:
    with pytest.raises(StorageError) as opened:
        store.open(ref, fmt)  # type: ignore[arg-type]
    assert _code(opened) is ErrorCode.STORAGE_PATH_REJECTED
    with pytest.raises(StorageError) as deleted:
        store.delete(ref, fmt)  # type: ignore[arg-type]
    assert _code(deleted) is ErrorCode.STORAGE_PATH_REJECTED


@pytest.mark.parametrize("fmt", ["pdf", "../x", None])
def test_save_refuses_untyped_formats(
    store: Store, root: CacheRoot, kind: str, fmt: object
) -> None:
    with pytest.raises(StorageError) as caught:
        store.save(fmt, _writer(DATA), max_bytes=100)  # type: ignore[arg-type]
    assert _code(caught) is ErrorCode.STORAGE_PATH_REJECTED
    assert _entries(root, kind) == []


def test_format_is_part_of_the_address(store: Store) -> None:
    stored = _save(store, fmt=PDF)
    with pytest.raises(StorageError):
        store.open(stored.ref, DOCX)


def test_input_and_output_stores_are_separate(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    stored = _save(input_store)
    with pytest.raises(StorageError):
        output_store.open(stored.ref, PDF)
    assert output_store.delete(stored.ref, PDF) is False
    input_store.verify(stored)


@pytest.mark.parametrize("tamper", ["modified", "truncated", "deleted"])
def test_verify_detects_tampering(store: Store, root: CacheRoot, kind: str, tamper: str) -> None:
    stored = _save(store)
    path = root.path / kind / f"{stored.ref.value}.pdf"
    if tamper == "deleted":
        path.unlink()
    else:
        path.chmod(0o600)
        path.write_bytes(DATA[::-1] if tamper == "modified" else DATA[:-1])
    with pytest.raises(StorageError) as caught:
        store.verify(stored)
    assert _code(caught) is ErrorCode.STORAGE_INTEGRITY_FAILED


def test_verify_detects_a_wrong_record(store: Store) -> None:
    stored = _save(store)
    wrong = StoredObject(stored.ref, PDF, Sha256Digest("0" * 64), stored.size_bytes)
    with pytest.raises(StorageError) as caught:
        store.verify(wrong)
    assert _code(caught) is ErrorCode.STORAGE_INTEGRITY_FAILED


# ------------------------------------------------------------------ delete


def test_delete_is_idempotent(store: Store, root: CacheRoot, kind: str) -> None:
    stored = _save(store)
    assert store.delete(stored.ref, PDF) is True
    assert store.delete(stored.ref, PDF) is False
    assert _entries(root, kind) == []


def test_delete_removes_a_planted_symlink_without_following_it(
    store: Store, root: CacheRoot, kind: str, outside: Path
) -> None:
    ref, path = _planted(root, kind)
    path.symlink_to(outside / "keep.txt")
    assert store.delete(ref, PDF) is True
    assert not path.is_symlink()
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"


# ------------------------------------------------------------------ interface shape


def test_no_store_method_accepts_a_name_or_path() -> None:
    for cls in (LocalInputStore, LocalOutputStore):
        for method_name, method in inspect.getmembers(cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            params = set(inspect.signature(method).parameters)
            assert not {p for p in params if "name" in p or "path" in p}, method_name


def test_stored_object_validates_fields() -> None:
    digest = Sha256Digest("a" * 64)
    for changes in (
        {"ref": uuid4()},
        {"document_format": "pdf"},
        {"sha256": "a" * 64},
        {"size_bytes": 0},
        {"size_bytes": HARD_MAX_FILE_BYTES + 1},
        {"size_bytes": True},
    ):
        fields: dict[str, object] = {
            "ref": ObjectRef(uuid4()),
            "document_format": PDF,
            "sha256": digest,
            "size_bytes": 1,
        }
        fields.update(changes)
        with pytest.raises(InvariantError):
            StoredObject(**fields)  # type: ignore[arg-type]


def test_storage_error_only_carries_storage_codes() -> None:
    assert StorageError(ErrorCode.STORAGE_WRITE_FAILED).code is ErrorCode.STORAGE_WRITE_FAILED
    with pytest.raises(InvariantError):
        StorageError(ErrorCode.INTERNAL_ERROR)
