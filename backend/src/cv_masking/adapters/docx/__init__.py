"""DOCX adapters. Archive is read in memory; XML is parsed with defusedxml."""

from cv_masking.adapters.docx.extractor import DocxExtractor
from cv_masking.adapters.docx.redactor import DocxXmlRedactor
from cv_masking.adapters.docx.verifier import DocxVerifier

__all__ = ["DocxExtractor", "DocxVerifier", "DocxXmlRedactor"]
