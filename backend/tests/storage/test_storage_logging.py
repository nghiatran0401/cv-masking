"""Storage log lines carry random IDs, kinds, codes, and counts only."""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import (
    LocalInputStore,
    LocalOutputStore,
    LocalStorageSweeper,
    LocalWorkArea,
    StorageRoot,
)
from cv_masking.domain.formats import DocumentFormat
from cv_masking.ports.storage import ObjectSink

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
ALLOWED_WORDS = {
    "stored",
    "deleted",
    "inputs",
    "outputs",
    "work",
    "object",
    "storage",
    "sweep",
    "removed",
    "temporary",
    "unexpected",
    "failed",
    "area",
    "cleanup",
    "deferred",
    "to",
    "sweeper",
    "code",
    "STORAGE_WRITE_FAILED",
    "directory",
    "permissions",
    "tightened",
    "owner-only",
}


def test_log_lines_contain_only_ids_kinds_codes_and_counts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    content = b"%PDF-1.7\n% synthetic Nguyen Van Mau 0900000000\n"
    with caplog.at_level(logging.DEBUG, logger="cv_masking.storage"):
        (tmp_path / "cache").mkdir(mode=0o755)
        root = StorageRoot.prepare(tmp_path / "cache")
        inputs, outputs = LocalInputStore(root), LocalOutputStore(root)
        stored = inputs.save_stream(DocumentFormat.PDF, [content], max_bytes=1000)

        def produce(sink: ObjectSink) -> None:
            sink.write(content)

        output = outputs.save(DocumentFormat.PDF, produce, max_bytes=1000)
        inputs.verify(stored)
        with LocalWorkArea(root).attempt() as directory:
            (directory / "part").write_bytes(content)
        inputs.delete(stored.ref, DocumentFormat.PDF)
        outputs.delete(output.ref, DocumentFormat.PDF)
        LocalStorageSweeper(root).sweep(datetime.now(UTC))

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) >= 5
    forbidden = (str(tmp_path), str(root.path), stored.sha256.value, "Nguyen", "0900000000")
    for message in messages:
        assert not any(fragment in message for fragment in forbidden), message
        for token in re.split(r"[\s=]+", UUID_RE.sub("", message)):
            assert token == "" or token.isdigit() or token in ALLOWED_WORDS, (token, message)
    assert any(str(stored.ref) in m for m in messages)
