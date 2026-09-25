"""Schema migrations, applied in order and recorded with a checksum.

A migration is never edited after release: the checksum of every applied
migration is re-checked on open, and the resulting schema must match exactly
what these migrations produce. A newer, foreign, edited, or extended schema
fails closed with STORAGE_INTEGRITY_FAILED.

Every text column is constrained to IDs, hashes, or code-like values, so no
column can hold free text such as names, content, or file names.
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from functools import cache
from typing import Final

from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256("\n;\n".join(self.statements).encode("utf-8")).hexdigest()


_BOOTSTRAP: Final = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY NOT NULL CHECK (version >= 1),
    checksum TEXT NOT NULL CHECK (length(checksum) = 64 AND checksum NOT GLOB '*[^0-9a-f]*')
) STRICT
"""

MIGRATIONS: Final = (
    Migration(
        1,
        (
            """
            CREATE TABLE batches (
                batch_id TEXT PRIMARY KEY NOT NULL
                    CHECK (length(batch_id) = 36 AND batch_id NOT GLOB '*[^0-9a-f-]*'),
                state TEXT NOT NULL
                    CHECK (length(state) BETWEEN 1 AND 32 AND state NOT GLOB '*[^a-z_]*'),
                mask_salary INTEGER NOT NULL CHECK (mask_salary IN (0, 1)),
                document_count INTEGER NOT NULL CHECK (document_count BETWEEN 0 AND 100),
                created_at INTEGER NOT NULL CHECK (created_at >= 0),
                updated_at INTEGER NOT NULL CHECK (updated_at >= created_at),
                version INTEGER NOT NULL CHECK (version >= 0)
            ) STRICT
            """,
            """
            CREATE TABLE documents (
                document_id TEXT PRIMARY KEY NOT NULL
                    CHECK (length(document_id) = 36 AND document_id NOT GLOB '*[^0-9a-f-]*'),
                batch_id TEXT NOT NULL REFERENCES batches (batch_id) ON DELETE CASCADE,
                state TEXT NOT NULL
                    CHECK (length(state) BETWEEN 1 AND 32 AND state NOT GLOB '*[^a-z_]*'),
                created_at INTEGER NOT NULL CHECK (created_at >= 0),
                updated_at INTEGER NOT NULL CHECK (updated_at >= created_at),
                version INTEGER NOT NULL CHECK (version >= 0),
                document_format TEXT
                    CHECK (length(document_format) BETWEEN 1 AND 8
                           AND document_format NOT GLOB '*[^a-z]*'),
                input_ref TEXT UNIQUE
                    CHECK (length(input_ref) = 36 AND input_ref NOT GLOB '*[^0-9a-f-]*'),
                content_sha256 TEXT
                    CHECK (length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
                size_bytes INTEGER CHECK (size_bytes BETWEEN 1 AND 20971520),
                uploaded_at INTEGER CHECK (uploaded_at >= created_at),
                attempt INTEGER NOT NULL CHECK (attempt BETWEEN 0 AND 3),
                policy_mask_salary INTEGER CHECK (policy_mask_salary IN (0, 1)),
                policy_version TEXT
                    CHECK (length(policy_version) BETWEEN 1 AND 16
                           AND policy_version NOT GLOB '*[^0-9.]*'),
                hidden_content_approved INTEGER NOT NULL CHECK (hidden_content_approved IN (0, 1)),
                findings_review_approved INTEGER NOT NULL
                    CHECK (findings_review_approved IN (0, 1)),
                output_ref TEXT UNIQUE
                    CHECK (length(output_ref) = 36 AND output_ref NOT GLOB '*[^0-9a-f-]*'),
                finding_counts_recorded INTEGER NOT NULL CHECK (finding_counts_recorded IN (0, 1)),
                verification_outcome TEXT
                    CHECK (length(verification_outcome) BETWEEN 1 AND 32
                           AND verification_outcome NOT GLOB '*[^a-z_]*'),
                verifier_id TEXT
                    CHECK (length(verifier_id) BETWEEN 1 AND 64
                           AND verifier_id NOT GLOB '*[^a-z0-9_.-]*'),
                verifier_version TEXT
                    CHECK (length(verifier_version) BETWEEN 5 AND 32
                           AND verifier_version NOT GLOB '*[^0-9.]*'),
                verified_at INTEGER CHECK (verified_at >= 0),
                error_code TEXT
                    CHECK (length(error_code) BETWEEN 1 AND 48
                           AND error_code NOT GLOB '*[^A-Z0-9_]*'),
                CHECK (output_ref IS NULL OR output_ref <> input_ref)
            ) STRICT
            """,
            "CREATE INDEX documents_by_batch ON documents (batch_id, created_at)",
            """
            CREATE TABLE document_finding_counts (
                document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
                entity_type TEXT NOT NULL
                    CHECK (length(entity_type) BETWEEN 1 AND 32
                           AND entity_type NOT GLOB '*[^a-z_]*'),
                count INTEGER NOT NULL CHECK (count >= 0),
                PRIMARY KEY (document_id, entity_type)
            ) STRICT, WITHOUT ROWID
            """,
            """
            CREATE TABLE document_review_reasons (
                document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
                reason TEXT NOT NULL
                    CHECK (length(reason) BETWEEN 1 AND 48 AND reason NOT GLOB '*[^A-Z_]*'),
                PRIMARY KEY (document_id, reason)
            ) STRICT, WITHOUT ROWID
            """,
            """
            CREATE TABLE document_verification_failures (
                document_id TEXT NOT NULL REFERENCES documents (document_id) ON DELETE CASCADE,
                code TEXT NOT NULL
                    CHECK (length(code) BETWEEN 1 AND 48 AND code NOT GLOB '*[^A-Z_]*'),
                PRIMARY KEY (document_id, code)
            ) STRICT, WITHOUT ROWID
            """,
        ),
    ),
)
LATEST_VERSION: Final = MIGRATIONS[-1].version


def _integrity_failure() -> StorageError:
    return StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED)


def _user_version(conn: sqlite3.Connection) -> int:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if not isinstance(version, int):
        raise _integrity_failure()
    return version


def _apply(conn: sqlite3.Connection, current: int) -> None:
    conn.execute(_BOOTSTRAP)
    for migration in MIGRATIONS[current:]:
        for statement in migration.statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (?, ?)",
            (migration.version, migration.checksum),
        )
    conn.execute(f"PRAGMA user_version = {int(LATEST_VERSION)}")


def schema_fingerprint(conn: sqlite3.Connection) -> str:
    rows = [
        tuple(row)
        for row in conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
        )
    ]
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


@cache
def expected_fingerprint() -> str:
    """The fingerprint of a database built from scratch by MIGRATIONS."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _apply(conn, 0)
        return schema_fingerprint(conn)
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    """Bring the database to LATEST_VERSION in one transaction, or refuse it."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = _user_version(conn)
        if not 0 <= current <= LATEST_VERSION:
            raise _integrity_failure()
        if current == 0 and conn.execute("SELECT count(*) FROM sqlite_schema").fetchone()[0]:
            raise _integrity_failure()
        if current > 0:
            applied = {
                row[0]: row[1]
                for row in conn.execute("SELECT version, checksum FROM schema_migrations")
            }
            expected = {m.version: m.checksum for m in MIGRATIONS[:current]}
            if applied != expected:
                raise _integrity_failure()
        if current < LATEST_VERSION:
            _apply(conn, current)
        if schema_fingerprint(conn) != expected_fingerprint():
            raise _integrity_failure()
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
