"""Database inspection: the schema can only hold IDs, hashes, codes, counts, and times."""

import sqlite3

import pytest
from domain_builders import T0, findings_review, new_batch_id, rebuild, verification_for, verifying

from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.domain.batch import Batch
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.verification import VerificationOutcome

EXPECTED_COLUMNS = {
    "schema_migrations": {"version", "checksum"},
    "batches": {
        "batch_id",
        "state",
        "mask_salary",
        "document_count",
        "created_at",
        "updated_at",
        "version",
    },
    "documents": {
        "document_id",
        "batch_id",
        "state",
        "created_at",
        "updated_at",
        "version",
        "document_format",
        "input_ref",
        "content_sha256",
        "size_bytes",
        "uploaded_at",
        "attempt",
        "policy_mask_salary",
        "policy_version",
        "hidden_content_approved",
        "findings_review_approved",
        "output_ref",
        "finding_counts_recorded",
        "verification_outcome",
        "verifier_id",
        "verifier_version",
        "verified_at",
        "error_code",
    },
    "document_finding_counts": {"document_id", "entity_type", "count"},
    "document_review_reasons": {"document_id", "reason"},
    "document_verification_failures": {"document_id", "code"},
}
FREE_TEXT = "Synthetic Candidate Nguyễn Văn Mẫu, 12 Phố Giả, synthetic@example.invalid"


def _tables(raw: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    names = [
        row[0]
        for row in raw.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        name: [(row[1], row[2]) for row in raw.execute(f"PRAGMA table_info({name})")]
        for name in names
    }


def _populate(store: SqliteMetadataStore) -> None:
    """One row in every table: a review with reasons, and a failed verification."""
    batch_id = new_batch_id()
    review = rebuild(findings_review(), batch_id=batch_id)
    job = verifying()
    failed = rebuild(
        job.record_verification(
            verification_for(
                job, VerificationOutcome.FAILED, frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING})
            ),
            job.updated_at,
        ),
        batch_id=batch_id,
    )
    batch = Batch.create(batch_id, T0).add_document(T0).add_document(T0)
    with store.transaction() as tx:
        tx.add_batch(batch)
        tx.add_document(review)
        tx.add_document(failed)


def test_tables_and_columns_are_exactly_the_allowlist(raw: sqlite3.Connection) -> None:
    tables = _tables(raw)
    assert {name: {column for column, _ in cols} for name, cols in tables.items()} == (
        EXPECTED_COLUMNS
    )
    assert {kind for cols in tables.values() for _, kind in cols} == {"INTEGER", "TEXT"}


def test_every_text_column_refuses_free_text(
    store: SqliteMetadataStore, raw: sqlite3.Connection
) -> None:
    _populate(store)
    text_columns = [
        (table, column)
        for table, columns in _tables(raw).items()
        for column, kind in columns
        if kind == "TEXT"
    ]
    assert len(text_columns) > 10
    for table, column in text_columns:
        assert raw.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= 1, table  # noqa: S608
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(f"UPDATE {table} SET {column} = ?", (FREE_TEXT,))  # noqa: S608
