"""SQLite implementation of the metadata port.

The database lives in ``<storage root>/metadata/``. The app creates the file
itself (owner-only), refuses a symlink or a file it does not own, and opens it
with ``mode=rw`` so SQLite never creates files of its own choosing. Every
transaction uses a fresh connection, so the store is safe to share across
threads; write transactions take the write lock up front (BEGIN IMMEDIATE).
"""

import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from cv_masking.adapters.local_storage.root import FILE_MODE, StorageRoot, require_owned_file
from cv_masking.adapters.sqlite import rows
from cv_masking.adapters.sqlite.migrations import migrate
from cv_masking.domain.batch import Batch
from cv_masking.domain.codes import INSPECTABLE_FAILURE_CODES, ErrorCode
from cv_masking.domain.document_job import TERMINAL_STATES, DocumentJob, DocumentState
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.ids import BatchId, DocumentId
from cv_masking.ports.metadata import (
    ConcurrentUpdateError,
    ObjectUse,
    RecordKind,
    RecordNotFoundError,
)
from cv_masking.ports.storage import StorageError

logger = logging.getLogger("cv_masking.metadata")

DATABASE_NAME: Final = "jobs.sqlite3"
SIDE_FILE_SUFFIXES: Final = ("-wal", "-shm")
BUSY_TIMEOUT_SECONDS: Final = 5.0

_CREATE_FILE: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)
_OPEN_CHECK: Final = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)
_PRAGMAS: Final = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA secure_delete = ON",
    "PRAGMA trusted_schema = OFF",
    "PRAGMA synchronous = FULL",
    "PRAGMA cell_size_check = ON",
)

_BATCH_SELECT: Final = f"SELECT {', '.join(rows.BATCH_COLUMNS)} FROM batches"  # noqa: S608
_DOCUMENT_SELECT: Final = f"SELECT {', '.join(rows.DOCUMENT_COLUMNS)} FROM documents"  # noqa: S608
_BATCH_INSERT: Final = (
    f"INSERT INTO batches ({', '.join(rows.BATCH_COLUMNS)}) "  # noqa: S608
    f"VALUES ({', '.join('?' for _ in rows.BATCH_COLUMNS)})"
)
_DOCUMENT_INSERT: Final = (
    f"INSERT INTO documents ({', '.join(rows.DOCUMENT_COLUMNS)}) "  # noqa: S608
    f"VALUES ({', '.join('?' for _ in rows.DOCUMENT_COLUMNS)})"
)
_BATCH_UPDATE: Final = (
    "UPDATE batches SET state = ?, mask_salary = ?, document_count = ?, updated_at = ?, "
    "version = ? WHERE batch_id = ? AND created_at = ? AND version = ?"
)
_DOCUMENT_MUTABLE: Final = rows.DOCUMENT_COLUMNS[2:]
_DOCUMENT_UPDATE: Final = (
    f"UPDATE documents SET {', '.join(f'{c} = ?' for c in _DOCUMENT_MUTABLE)} "  # noqa: S608
    "WHERE document_id = ? AND batch_id = ? AND created_at = ? AND version = ?"
)


def _storage_error(error: sqlite3.Error) -> StorageError:
    if isinstance(error, sqlite3.IntegrityError):
        return StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED)
    if isinstance(error, sqlite3.OperationalError):
        return StorageError(ErrorCode.STORAGE_WRITE_FAILED)
    if isinstance(error, sqlite3.DatabaseError):
        return StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED)
    return StorageError(ErrorCode.STORAGE_WRITE_FAILED)


@contextmanager
def _translated() -> Iterator[None]:
    try:
        yield
    except sqlite3.Error as error:
        raise _storage_error(error) from error


class _Reader:
    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_batch(self, batch_id: BatchId) -> Batch:
        row = self._conn.execute(f"{_BATCH_SELECT} WHERE batch_id = ?", (str(batch_id),)).fetchone()
        if row is None:
            raise RecordNotFoundError(RecordKind.BATCH)
        return rows.batch_from_row(rows.as_row(row))

    def list_batches(self) -> tuple[Batch, ...]:
        found = self._conn.execute(f"{_BATCH_SELECT} ORDER BY created_at, batch_id").fetchall()
        return tuple(rows.batch_from_row(rows.as_row(row)) for row in found)

    def get_document(self, document_id: DocumentId) -> DocumentJob:
        key = str(document_id)
        row = self._conn.execute(f"{_DOCUMENT_SELECT} WHERE document_id = ?", (key,)).fetchone()
        if row is None:
            raise RecordNotFoundError(RecordKind.DOCUMENT)
        return self._document(rows.as_row(row))

    def list_documents(self, batch_id: BatchId) -> tuple[DocumentJob, ...]:
        found = self._conn.execute(
            f"{_DOCUMENT_SELECT} WHERE batch_id = ? ORDER BY created_at, document_id",
            (str(batch_id),),
        ).fetchall()
        return tuple(self._document(rows.as_row(row)) for row in found)

    def input_uses(self) -> tuple[ObjectUse, ...]:
        found = self._conn.execute(
            "SELECT input_ref, document_format, state FROM documents WHERE input_ref IS NOT NULL"
        ).fetchall()
        return tuple(
            ObjectUse(
                rows.object_ref(ref),
                rows.document_format(fmt),
                needed=rows.document_state(state) not in TERMINAL_STATES,
            )
            for ref, fmt, state in found
        )

    def output_uses(self) -> tuple[ObjectUse, ...]:
        found = self._conn.execute(
            "SELECT output_ref, document_format, state, error_code "
            "FROM documents WHERE output_ref IS NOT NULL"
        ).fetchall()
        return tuple(
            ObjectUse(
                rows.object_ref(ref),
                rows.document_format(fmt),
                needed=_output_needed(rows.document_state(state), error_code),
            )
            for ref, fmt, state, error_code in found
        )

    def _document(self, row: rows.Row) -> DocumentJob:
        key = (row["document_id"],)
        counts = self._children(
            "SELECT entity_type, count FROM document_finding_counts WHERE document_id = ?", key
        )
        reasons = self._children(
            "SELECT reason FROM document_review_reasons WHERE document_id = ?", key
        )
        failures = self._children(
            "SELECT code FROM document_verification_failures WHERE document_id = ?", key
        )
        hidden = self._children(
            "SELECT category, count FROM document_hidden_content WHERE document_id = ?", key
        )
        residual = self._children(
            "SELECT entity_type, count FROM document_residual_counts WHERE document_id = ?", key
        )
        residual_pages = self._children(
            "SELECT entity_type, page FROM document_residual_pages WHERE document_id = ?", key
        )
        return rows.document_from_rows(
            row, counts, reasons, failures, hidden, residual, residual_pages
        )

    def _children(self, sql: str, key: tuple[object, ...]) -> list[rows.Row]:
        return [rows.as_row(row) for row in self._conn.execute(sql, key).fetchall()]


class _Transaction(_Reader):
    __slots__ = ()

    def add_batch(self, batch: Batch) -> None:
        self._conn.execute(_BATCH_INSERT, rows.batch_params(batch))

    def update_batch(self, batch: Batch, *, expected_version: int) -> None:
        _require_advance(batch.version, expected_version)
        cursor = self._conn.execute(
            _BATCH_UPDATE,
            (
                batch.state.value,
                int(batch.mask_salary),
                batch.document_count,
                rows.to_micros(batch.updated_at),
                batch.version,
                str(batch.batch_id),
                rows.to_micros(batch.created_at),
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            self._raise_missing_or_conflict(
                "batches", "batch_id", str(batch.batch_id), RecordKind.BATCH
            )

    def delete_batch(self, batch_id: BatchId) -> None:
        cursor = self._conn.execute("DELETE FROM batches WHERE batch_id = ?", (str(batch_id),))
        if cursor.rowcount != 1:
            raise RecordNotFoundError(RecordKind.BATCH)

    def add_document(self, job: DocumentJob) -> None:
        self._conn.execute(_DOCUMENT_INSERT, rows.document_params(job))
        self._write_children(job)

    def update_document(self, job: DocumentJob, *, expected_version: int) -> None:
        _require_advance(job.version, expected_version)
        params = rows.document_params(job)
        cursor = self._conn.execute(
            _DOCUMENT_UPDATE,
            (*params[2:], params[0], params[1], params[3], expected_version),
        )
        if cursor.rowcount != 1:
            self._raise_missing_or_conflict(
                "documents", "document_id", str(job.document_id), RecordKind.DOCUMENT
            )
        for table in (
            "document_finding_counts",
            "document_review_reasons",
            "document_verification_failures",
            "document_hidden_content",
            "document_residual_counts",
            "document_residual_pages",
        ):
            self._conn.execute(
                f"DELETE FROM {table} WHERE document_id = ?",  # noqa: S608 - fixed table names
                (str(job.document_id),),
            )
        self._write_children(job)

    def delete_document(self, document_id: DocumentId) -> None:
        cursor = self._conn.execute(
            "DELETE FROM documents WHERE document_id = ?", (str(document_id),)
        )
        if cursor.rowcount != 1:
            raise RecordNotFoundError(RecordKind.DOCUMENT)

    def _write_children(self, job: DocumentJob) -> None:
        self._conn.executemany(
            "INSERT INTO document_finding_counts (document_id, entity_type, count) "
            "VALUES (?, ?, ?)",
            rows.finding_count_params(job),
        )
        self._conn.executemany(
            "INSERT INTO document_review_reasons (document_id, reason) VALUES (?, ?)",
            rows.review_reason_params(job),
        )
        self._conn.executemany(
            "INSERT INTO document_verification_failures (document_id, code) VALUES (?, ?)",
            rows.verification_failure_params(job),
        )
        self._conn.executemany(
            "INSERT INTO document_hidden_content (document_id, category, count) VALUES (?, ?, ?)",
            rows.hidden_content_params(job),
        )
        self._conn.executemany(
            "INSERT INTO document_residual_counts (document_id, entity_type, count) "
            "VALUES (?, ?, ?)",
            rows.residual_count_params(job),
        )
        self._conn.executemany(
            "INSERT INTO document_residual_pages (document_id, entity_type, page) VALUES (?, ?, ?)",
            rows.residual_page_params(job),
        )

    def _raise_missing_or_conflict(
        self, table: str, key_column: str, key: str, kind: RecordKind
    ) -> None:
        exists = self._conn.execute(
            f"SELECT 1 FROM {table} WHERE {key_column} = ?",  # noqa: S608 - fixed identifiers
            (key,),
        ).fetchone()
        if exists is None:
            raise RecordNotFoundError(kind)
        raise ConcurrentUpdateError(kind)


def _require_advance(new_version: int, expected_version: int) -> None:
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise InvariantError("expected_version must be an integer")
    if new_version <= expected_version:
        raise InvariantError("an update must advance the record version")


class SqliteMetadataStore:
    """Build with ``open``; it checks the files, the schema, and the migrations."""

    __slots__ = ("_path", "_root")

    def __init__(self, root: StorageRoot, path: Path) -> None:
        self._root = root
        self._path = path

    @classmethod
    def open(cls, root: StorageRoot) -> "SqliteMetadataStore":
        with root.open_metadata() as directory:
            try:
                os.close(directory.open(DATABASE_NAME, _CREATE_FILE, FILE_MODE))
            except FileExistsError:
                pass
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
        store = cls(root, root.metadata_path / DATABASE_NAME)
        conn = store._connect()
        try:
            with _translated():
                if conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] != "wal":
                    raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)
                if [tuple(row) for row in conn.execute("PRAGMA quick_check")] != [("ok",)]:
                    raise StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED)
                migrate(conn)
        finally:
            conn.close()
        logger.info("metadata store opened")
        return store

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def read(self) -> Iterator[_Reader]:
        """A consistent read-only snapshot."""
        conn = self._connect()
        try:
            with _translated():
                conn.execute("PRAGMA query_only = ON")
                conn.execute("BEGIN DEFERRED")
            try:
                with _translated():
                    yield _Reader(conn)
            finally:
                with _translated():
                    conn.execute("ROLLBACK")
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[_Transaction]:
        conn = self._connect()
        try:
            with _translated():
                conn.execute("BEGIN IMMEDIATE")
            try:
                with _translated():
                    yield _Transaction(conn)
                    conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    with _translated():
                        conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def compact(self) -> None:
        """Move committed changes out of the WAL and truncate it (used after deletions)."""
        conn = self._connect()
        try:
            with _translated():
                busy, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy:
                logger.warning(
                    "metadata checkpoint deferred code=%s", ErrorCode.STORAGE_WRITE_FAILED
                )
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        self._check_files()
        try:
            conn = sqlite3.connect(
                f"{self._path.as_uri()}?mode=rw",
                uri=True,
                timeout=BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
            )
        except sqlite3.Error as error:
            raise _storage_error(error) from error
        try:
            with _translated():
                conn.row_factory = sqlite3.Row
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DDL, False)
                conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)
                for pragma in _PRAGMAS:
                    conn.execute(pragma)
        except BaseException:
            conn.close()
            raise
        return conn

    def _check_files(self) -> None:
        """The database and its side files must be private regular files owned by this user."""
        with self._root.open_metadata() as directory:
            for suffix in ("", *SIDE_FILE_SUFFIXES):
                try:
                    fd = directory.open(DATABASE_NAME + suffix, _OPEN_CHECK)
                except FileNotFoundError as error:
                    if suffix:
                        continue
                    raise StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED) from error
                except OSError as error:
                    raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
                try:
                    # Another connection closing may unlink a side file between the
                    # open and the check; an unlinked file is never reused.
                    if suffix and os.fstat(fd).st_nlink == 0:
                        continue
                    require_owned_file(fd)
                finally:
                    os.close(fd)


def _output_needed(state: DocumentState, error_code: object) -> bool:
    if state in {DocumentState.REJECTED, DocumentState.CANCELLED}:
        return False
        if state is DocumentState.FAILED:
            if not isinstance(error_code, str):
                return False
            try:
                return ErrorCode(error_code) in INSPECTABLE_FAILURE_CODES
            except ValueError:
                return False
    return True
