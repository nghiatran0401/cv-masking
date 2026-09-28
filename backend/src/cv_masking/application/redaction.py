"""Redact a stored input into new output bytes. The input is never modified.

The output is stored by the worker's supervisor, not here, so the process
that parses the untrusted input only ever reads stored files.
"""

import logging
from collections.abc import Callable

from cv_masking.application.detection import DetectionOutcome
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.ports.redaction import DocxRedactor, PdfRedactor, RedactionResult
from cv_masking.ports.storage import InputStore, StorageError, StoredObject

logger = logging.getLogger("cv_masking.redaction")


class RedactionOutcome:
    __slots__ = ("failure", "labelled_regions", "output", "solid_regions")

    def __init__(
        self,
        output: bytes | None,
        failure: ErrorCode | None,
        labelled_regions: int = 0,
        solid_regions: int = 0,
    ) -> None:
        if (output is None) == (failure is None):
            raise InvariantError("RedactionOutcome needs exactly one of output or failure")
        self.output = output
        self.failure = failure
        self.labelled_regions = labelled_regions
        self.solid_regions = solid_regions


class RedactionService:
    __slots__ = ("_docx", "_inputs", "_pdf")

    def __init__(
        self,
        inputs: InputStore,
        *,
        pdf: PdfRedactor | None = None,
        docx: DocxRedactor | None = None,
    ) -> None:
        self._inputs = inputs
        self._pdf = pdf
        self._docx = docx

    def redact(self, source: StoredObject, detection: DetectionOutcome) -> RedactionOutcome:
        """New output bytes for ``source`` from the detection regions or DOCX ranges.

        The source hash is checked before it is read. Hidden content is always
        removed (D-32).
        """
        if detection.failure is not None:
            raise InvariantError("redaction needs a successful detection outcome")
        fmt = source.document_format
        run = self._runner(fmt, detection)
        try:
            self._inputs.verify(source)
            with self._inputs.open(source.ref, fmt) as handle:
                data = handle.read()
        except StorageError as error:
            logger.info("redaction input unavailable")
            return RedactionOutcome(None, error.code)
        result = run(data)
        if result.failure is not None or result.output is None:
            logger.info("redaction failed")
            return RedactionOutcome(None, result.failure or ErrorCode.REDACT_FAILED)
        logger.info(
            "redaction applied regions=%d labelled=%d solid=%d",
            len(detection.regions) + len(detection.docx_ranges),
            result.labelled_regions,
            result.solid_regions,
        )
        return RedactionOutcome(result.output, None, result.labelled_regions, result.solid_regions)

    def _runner(
        self, fmt: DocumentFormat, detection: DetectionOutcome
    ) -> Callable[[bytes], RedactionResult]:
        pdf, docx = self._pdf, self._docx
        if fmt is DocumentFormat.PDF and pdf is not None:
            return lambda data: pdf.redact(data, detection.regions)
        if fmt is DocumentFormat.DOCX and docx is not None:
            return lambda data: docx.redact(data, detection.docx_ranges)
        raise InvariantError("redaction has no redactor for this document format")
