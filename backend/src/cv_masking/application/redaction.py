"""Redact a stored input into a new stored output. The input is never modified.

The job state transitions around this call (``start_processing``,
``output_written``) belong to the Stage 12 worker.
"""

import logging
from collections.abc import Callable

from cv_masking.application.detection import DetectionOutcome
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.redaction import DocxRedactor, PdfRedactor, RedactionResult
from cv_masking.ports.storage import InputStore, ObjectSink, OutputStore, StorageError, StoredObject

logger = logging.getLogger("cv_masking.redaction")


class RedactionOutcome:
    __slots__ = ("failure", "labelled_regions", "output", "solid_regions")

    def __init__(
        self,
        output: StoredObject | None,
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
    __slots__ = ("_docx", "_inputs", "_outputs", "_pdf")

    def __init__(
        self,
        inputs: InputStore,
        outputs: OutputStore,
        *,
        pdf: PdfRedactor | None = None,
        docx: DocxRedactor | None = None,
    ) -> None:
        self._inputs = inputs
        self._outputs = outputs
        self._pdf = pdf
        self._docx = docx

    def redact(
        self, source: StoredObject, detection: DetectionOutcome, *, remove_hidden: bool
    ) -> RedactionOutcome:
        """Write a new output for ``source`` from the detection regions or DOCX ranges.

        ``remove_hidden`` is True only when HR approved the hidden-content alert.
        The source hash is checked before reading and again after the output is
        stored; a mismatch deletes the output.
        """
        if detection.failure is not None:
            raise InvariantError("redaction needs a successful detection outcome")
        fmt = source.document_format
        run = self._runner(fmt, detection, remove_hidden=remove_hidden)
        try:
            self._inputs.verify(source)
            with self._inputs.open(source.ref, fmt) as handle:
                data = handle.read()
        except StorageError as error:
            logger.info("redaction input unavailable")
            return RedactionOutcome(None, error.code)
        result = run(data)
        output = result.output
        if result.failure is not None or output is None:
            logger.info("redaction failed")
            return RedactionOutcome(None, result.failure or ErrorCode.REDACT_FAILED)

        def produce(sink: ObjectSink) -> None:
            sink.write(output)

        try:
            stored = self._outputs.save(fmt, produce, max_bytes=HARD_MAX_FILE_BYTES)
        except StorageError:
            logger.info("redaction output write failed")
            return RedactionOutcome(None, ErrorCode.REDACT_OUTPUT_WRITE_FAILED)
        try:
            self._inputs.verify(source)
        except StorageError as error:
            self._outputs.delete(stored.ref, fmt)
            logger.info("redaction input changed during redaction")
            return RedactionOutcome(None, error.code)
        logger.info(
            "redaction written regions=%d labelled=%d solid=%d",
            len(detection.regions) + len(detection.docx_ranges),
            result.labelled_regions,
            result.solid_regions,
        )
        return RedactionOutcome(stored, None, result.labelled_regions, result.solid_regions)

    def _runner(
        self, fmt: DocumentFormat, detection: DetectionOutcome, *, remove_hidden: bool
    ) -> Callable[[bytes], RedactionResult]:
        pdf, docx = self._pdf, self._docx
        if fmt is DocumentFormat.PDF and pdf is not None:
            return lambda data: pdf.redact(data, detection.regions, remove_hidden=remove_hidden)
        if fmt is DocumentFormat.DOCX and docx is not None:
            return lambda data: docx.redact(
                data, detection.docx_ranges, remove_hidden=remove_hidden
            )
        raise InvariantError("redaction has no redactor for this document format")
