import json
import logging
from pathlib import Path

import pytest

from cv_masking.evaluation.__main__ import main
from cv_masking.evaluation.fixtures import SENTINELS, annotated_docx, annotated_pdf
from cv_masking.evaluation.harness import AUTHORIZED_ENV, run_authorized, run_synthetic
from cv_masking.evaluation.report import canonical_dict, report_json, report_markdown


def test_synthetic_report_is_metadata_only_and_split_by_format(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        report = run_synthetic()
    payload = report_json(report)
    markdown = report_markdown(report)
    logged = " ".join(record.getMessage() for record in caplog.records)
    combined = payload + markdown + logged
    for sentinel in SENTINELS:
        assert sentinel not in combined
    body = json.loads(payload)
    assert body["set"] == "synthetic"
    assert body["photos_and_images_unmasked"] is True
    formats = {item["format"]: item for item in body["by_format"]}
    assert set(formats) == {"pdf", "docx"}
    for item in formats.values():
        assert item["documents"] == 2
        assert item["failed"] == 1
        assert item["failure_rate"] == 0.5
        assert item["duration_ms"] >= 0
        assert item["leaked_distinctive"] == 0
        assert "entities" in item
    assert "Photos and embedded images are **not masked**" in markdown


def test_synthetic_metrics_are_reproducible() -> None:
    first = canonical_dict(run_synthetic())
    second = canonical_dict(run_synthetic())
    assert first == second
    pdf_entities = first["by_format"][0]["entities"]
    assert pdf_entities
    assert pdf_entities["gender"]["gold"] == 1
    assert pdf_entities["ethnicity"]["gold"] == 1
    for scores in pdf_entities.values():
        assert scores["false_negative"] >= 0
        assert scores["gold"] >= 0


def test_authorized_is_refused_without_the_env(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        run_authorized(tmp_path)


def test_authorized_report_has_no_paths_or_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUTHORIZED_ENV, "1")
    (tmp_path / "synthetic-eval.pdf").write_bytes(annotated_pdf())
    (tmp_path / "synthetic-eval.docx").write_bytes(annotated_docx())
    report = run_authorized(tmp_path)
    payload = report_json(report)
    assert report.set_name == "authorized"
    assert str(tmp_path) not in payload
    assert "synthetic-eval" not in payload
    for sentinel in SENTINELS:
        assert sentinel not in payload
    body = json.loads(payload)
    pdf = next(item for item in body["by_format"] if item["format"] == "pdf")
    assert pdf["documents"] == 1
    assert pdf["entities"] == {}


def test_cli_authorized_is_refused_without_the_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(AUTHORIZED_ENV, raising=False)
    with pytest.raises(PermissionError):
        main(["--authorized", str(tmp_path)])
