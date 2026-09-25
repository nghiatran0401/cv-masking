from pathlib import Path

from synthetic_files import SYNTHETIC_PDF, synthetic_docx

from cv_masking.application.identify import IdentifiedKind, declared_disagrees, identify_file


def _write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "upload.bin"
    path.write_bytes(data)
    return path


def test_identify_pdf_docx_macro_and_ole(tmp_path: Path) -> None:
    assert identify_file(_write(tmp_path, SYNTHETIC_PDF)) is IdentifiedKind.PDF
    assert identify_file(_write(tmp_path, synthetic_docx())) is IdentifiedKind.DOCX
    assert (
        identify_file(_write(tmp_path, synthetic_docx(macro=True)))
        is IdentifiedKind.MACRO_OR_TEMPLATE
    )
    assert identify_file(_write(tmp_path, bytes.fromhex("d0cf11e0a1b11ae1") + b"x")) is (
        IdentifiedKind.UNSUPPORTED
    )


def test_spoofed_declaration_is_detected() -> None:
    assert declared_disagrees(
        IdentifiedKind.PDF, filename="synthetic.docx", content_type="application/pdf"
    )
    assert declared_disagrees(
        IdentifiedKind.PDF, filename="synthetic.pdf", content_type="image/jpeg"
    )
    assert not declared_disagrees(
        IdentifiedKind.PDF, filename="synthetic.pdf", content_type="application/pdf"
    )
    assert not declared_disagrees(IdentifiedKind.DOCX, filename=None, content_type=None)
