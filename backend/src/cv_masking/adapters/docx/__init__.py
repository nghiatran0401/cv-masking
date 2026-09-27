"""DOCX adapters. Archive is read in memory; XML is parsed with defusedxml."""

from cv_masking.adapters.docx.extractor import DocxExtractor
from cv_masking.adapters.docx.redactor import DocxXmlRedactor

__all__ = ["DocxExtractor", "DocxXmlRedactor"]
