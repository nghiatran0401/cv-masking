"""Allowlisted CV URL parsing. No network."""

from cv_masking.domain.source_url import (
    MAX_SOURCE_URL_LENGTH,
    SOURCE_CV_HOST,
    parse_cv_source_url,
)

PDF = f"https://{SOURCE_CV_HOST}/2026/synthetic-cv.pdf"


def test_accepts_pdf_and_docx_and_keeps_the_query() -> None:
    parsed = parse_cv_source_url(f"{PDF}?token=synthetic")
    assert parsed is not None
    assert parsed.href == f"{PDF}?token=synthetic"
    assert parsed.filename == "synthetic-cv.pdf"
    docx = parse_cv_source_url(f"https://{SOURCE_CV_HOST}/folder/Synthetic.DOCX")
    assert docx is not None
    assert docx.filename == "Synthetic.docx"


def test_canonicalizes_an_explicit_443_port() -> None:
    parsed = parse_cv_source_url(f"https://{SOURCE_CV_HOST}:443/2026/synthetic-cv.pdf")
    assert parsed is not None
    assert parsed.href == PDF


def test_refuses_other_hosts_schemes_ports_and_credentials() -> None:
    refused = [
        f"http://{SOURCE_CV_HOST}/2026/synthetic-cv.pdf",
        "https://intranet.example.invalid/synthetic-cv.pdf",
        f"https://user:synthetic@{SOURCE_CV_HOST}/2026/synthetic-cv.pdf",
        f"https://{SOURCE_CV_HOST}:8443/2026/synthetic-cv.pdf",
        f"https://{SOURCE_CV_HOST}/2026/synthetic-cv.doc",
        f"https://{SOURCE_CV_HOST}/2026/../synthetic-cv.pdf",
        f"https://{SOURCE_CV_HOST}/2026/%2e%2e/synthetic-cv.pdf",
        f"https://{SOURCE_CV_HOST}/2026/.pdf",
        "javascript:alert(1)",
        "file:///tmp/synthetic-cv.pdf",
        PDF + "#page=1",
        "https://" + SOURCE_CV_HOST.upper() + ".evil.example/synthetic-cv.pdf",
        "x" * (MAX_SOURCE_URL_LENGTH + 1),
        "",
    ]
    assert [parse_cv_source_url(item) for item in refused] == [None] * len(refused)


def test_hostname_constant_has_no_scheme() -> None:
    assert "://" not in SOURCE_CV_HOST
