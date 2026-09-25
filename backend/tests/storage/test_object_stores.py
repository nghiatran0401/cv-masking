import hashlib
import inspect
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.adapters.local_storage import stores as stores_module
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import ObjectRef, Sha256Digest
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.storage import ObjectSink, StorageError

PDF = DocumentFormat.PDF
DOCX = DocumentFormat.DOCX
DATA = b"%PDF-1.7\n% synthetic test object\n" * 10


def _writer(*chunks: bytes) -> Callable[[ObjectSink], None]:
    def produce(sink: ObjectSink) -> None:
        for chunk in chunks:
            sink.write(chunk)

    return produce


def _entries(root: StorageRoot, kind: str) -> list[str]:
    return sorted(path.name for path in (root.path / kind).iterdir())


def _planted(root: StorageRoot) -> tuple[ObjectRef, Path]:
    ref = ObjectRef(uuid4())
    return ref, root.path / "inputs" / f"{ref.value}.pdf"


def test_save_round_trips_read_only_with_hash_and_size(
    input_store: LocalInputStore, output_store: LocalOutputStore, root: StorageRoot
) -> None:
    for kind, store in (("inputs", input_store), ("outputs", output_store)):
        stored = store.save(DOCX, _writer(DATA), max_bytes=HARD_MAX_FILE_BYTES)
        assert stored.sha256 == Sha256Digest(hashlib.sha256(DATA).hexdigest())
        assert stored.size_bytes == len(DATA)
        assert _entries(root, kind) == [f"{stored.ref.value}.docx"]
        assert stat.S_IMODE((root.path / kind / f"{stored.ref.value}.docx").stat().st_mode) == 0o400
        with store.open(stored.ref, DOCX) as file:
            assert file.read() == DATA
        store.verify(stored)


def test_size_limit_is_exact(input_store: LocalInputStore, root: StorageRoot) -> None:
    assert input_store.save(PDF, _writer(DATA), max_bytes=len(DATA)).size_bytes == len(DATA)
    with pytest.raises(StorageError) as caught:
        input_store.save(PDF, _writer(DATA, b"x"), max_bytes=len(DATA))
    assert caught.value.code is ErrorCode.UPLOAD_FILE_TOO_LARGE
    assert len(_entries(root, "inputs")) == 1


def test_interrupted_upload_leaves_nothing_behind(
    input_store: LocalInputStore, root: StorageRoot
) -> None:
    def chunks() -> Iterator[bytes]:
        yield DATA
        raise ConnectionResetError("synthetic client disconnect")

    with pytest.raises(StorageError):
        input_store.save_stream(PDF, chunks(), max_bytes=HARD_MAX_FILE_BYTES)
    assert _entries(root, "inputs") == []


def test_save_never_overwrites_an_existing_object(
    input_store: LocalInputStore, root: StorageRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = UUID("12345678-1234-4234-8234-123456789abc")
    temp = UUID("abcdefab-cdef-4abc-8def-abcdefabcdef")
    values = iter([fixed, temp])
    monkeypatch.setattr(stores_module, "uuid4", lambda: next(values))
    existing = root.path / "inputs" / f"{fixed}.pdf"
    existing.write_bytes(b"synthetic existing object")
    with pytest.raises(StorageError):
        input_store.save(PDF, _writer(DATA), max_bytes=HARD_MAX_FILE_BYTES)
    assert existing.read_bytes() == b"synthetic existing object"
    assert _entries(root, "inputs") == [existing.name]


def test_unsafe_files_at_an_object_name_are_refused(
    input_store: LocalInputStore, root: StorageRoot, outside: Path
) -> None:
    symlinked, path = _planted(root)
    path.symlink_to(outside / "keep.txt")
    readable, path = _planted(root)
    path.write_bytes(DATA)
    path.chmod(0o644)
    hard_linked, path = _planted(root)
    os.link(outside / "keep.txt", path)
    for ref in (symlinked, readable, hard_linked):
        with pytest.raises(StorageError) as caught:
            input_store.open(ref, PDF)
        assert caught.value.code is ErrorCode.STORAGE_PATH_REJECTED


def test_untyped_refs_and_formats_are_refused(input_store: LocalInputStore) -> None:
    for ref, fmt in ((uuid4(), PDF), ("../../etc/passwd", PDF), (ObjectRef(uuid4()), "../x")):
        with pytest.raises(StorageError) as caught:
            input_store.open(ref, fmt)  # type: ignore[arg-type]
        assert caught.value.code is ErrorCode.STORAGE_PATH_REJECTED


def test_input_and_output_stores_are_separate(
    input_store: LocalInputStore, output_store: LocalOutputStore
) -> None:
    stored = input_store.save(PDF, _writer(DATA), max_bytes=HARD_MAX_FILE_BYTES)
    with pytest.raises(StorageError):
        output_store.open(stored.ref, PDF)
    assert output_store.delete(stored.ref, PDF) is False
    input_store.verify(stored)


def test_verify_detects_tampering(input_store: LocalInputStore, root: StorageRoot) -> None:
    stored = input_store.save(PDF, _writer(DATA), max_bytes=HARD_MAX_FILE_BYTES)
    path = root.path / "inputs" / f"{stored.ref.value}.pdf"
    path.chmod(0o600)
    path.write_bytes(DATA[::-1])
    with pytest.raises(StorageError) as caught:
        input_store.verify(stored)
    assert caught.value.code is ErrorCode.STORAGE_INTEGRITY_FAILED


def test_delete_removes_a_planted_symlink_without_following_it(
    input_store: LocalInputStore, root: StorageRoot, outside: Path
) -> None:
    ref, path = _planted(root)
    path.symlink_to(outside / "keep.txt")
    assert input_store.delete(ref, PDF) is True
    assert not path.is_symlink()
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"


def test_list_objects_reports_only_regular_stored_objects(
    input_store: LocalInputStore, root: StorageRoot, outside: Path
) -> None:
    stored = input_store.save(DOCX, _writer(DATA), max_bytes=HARD_MAX_FILE_BYTES)
    _, link = _planted(root)
    link.symlink_to(outside / "keep.txt")
    (root.path / "inputs" / "notes.txt").write_bytes(b"synthetic")
    (listing,) = input_store.list_objects()
    assert (listing.ref, listing.document_format) == (stored.ref, DOCX)
    assert listing.modified_at.utcoffset() is not None


def test_no_store_method_accepts_a_name_or_path() -> None:
    for cls in (LocalInputStore, LocalOutputStore):
        for method_name, method in inspect.getmembers(cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            params = set(inspect.signature(method).parameters)
            assert not {p for p in params if "name" in p or "path" in p}, method_name
