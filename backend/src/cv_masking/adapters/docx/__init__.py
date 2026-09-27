"""DOCX adapters. Archive is read in memory; XML is parsed with defusedxml."""

from cv_masking.adapters.docx.extractor import DocxExtractor

__all__ = ["DocxExtractor"]
