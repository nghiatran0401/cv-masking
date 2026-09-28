"""One document's pipeline as it runs inside the worker: validate, process, verify.

The extracted text and the findings live in this object's memory between the
three calls and are dropped when verification ends or the next document
begins. Nothing here writes metadata or stored files; the supervisor does.
"""

import logging
from collections.abc import Mapping

from cv_masking.application.detection import DetectionOutcome, DetectionService
from cv_masking.application.redaction import RedactionService
from cv_masking.application.verification import VerificationService
from cv_masking.domain.codes import ERROR_CODE_GROUPS, CodeGroup, ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCounts
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.ports.extraction import DocumentExtractor, ExtractedDocument
from cv_masking.ports.processing import ProcessingReport, ValidationReport, VerificationReport
from cv_masking.ports.storage import InputStore, StorageError, StoredObject

logger = logging.getLogger("cv_masking.processing")


class DocumentPipeline:
    __slots__ = (
        "_detected",
        "_detection",
        "_document",
        "_extractors",
        "_inputs",
        "_policy",
        "_redaction",
        "_source",
        "_verification",
    )

    def __init__(
        self,
        inputs: InputStore,
        extractors: Mapping[DocumentFormat, DocumentExtractor],
        detection: DetectionService,
        redaction: RedactionService,
        verification: VerificationService,
    ) -> None:
        self._inputs = inputs
        self._extractors = dict(extractors)
        self._detection = detection
        self._redaction = redaction
        self._verification = verification
        self._source: StoredObject | None = None
        self._document: ExtractedDocument | None = None
        self._detected: DetectionOutcome | None = None
        self._policy: MaskingPolicy | None = None

    def validate(self, source: StoredObject) -> ValidationReport:
        """Classify and extract. Hidden content is reported, not a reason to stop (D-32)."""
        self.forget()
        extractor = self._extractors.get(source.document_format)
        if extractor is None:
            raise InvariantError("validation has no extractor for this document format")
        try:
            self._inputs.verify(source)
            with self._inputs.open(source.ref, source.document_format) as handle:
                data = handle.read()
        except StorageError as error:
            logger.info("validation input unavailable")
            return ValidationReport(failure=error.code)
        result = extractor.extract(data)
        if result.failure is not None:
            code = result.failure
            if ERROR_CODE_GROUPS[code] is not CodeGroup.VALIDATION:
                code = ErrorCode.INTERNAL_ERROR
            logger.info("validation failed")
            return ValidationReport(failure=code)
        if result.review:
            logger.info("validation review reasons=%d", len(result.review))
            return ValidationReport(review=result.review)
        if result.document is None:
            return ValidationReport(failure=ErrorCode.INTERNAL_ERROR)
        self._source, self._document = source, result.document
        hidden = HiddenContentCounts.from_alerts(result.document.hidden)
        logger.info(
            "validation passed parts=%d hidden=%d", len(result.document.parts), len(hidden.items)
        )
        return ValidationReport(hidden_removed=hidden)

    def process(self, policy: MaskingPolicy) -> ProcessingReport:
        """Detect and redact; the output bytes go back to the supervisor to store."""
        source, document = self._source, self._document
        if source is None or document is None or self._detected is not None:
            raise InvariantError("processing needs a validated document")
        detection = self._detection.detect(document, policy)
        if detection.failure is not None:
            return ProcessingReport(failure=detection.failure)
        outcome = self._redaction.redact(source, detection)
        if outcome.failure is not None or outcome.output is None:
            return ProcessingReport(failure=outcome.failure or ErrorCode.REDACT_FAILED)
        self._detected, self._policy = detection, policy
        return ProcessingReport(
            output=outcome.output, finding_counts=detection.counts, review=detection.review
        )

    def verify(self, output: StoredObject) -> VerificationReport:
        """Independently check the stored output, then forget the document."""
        source, document = self._source, self._document
        detected, policy = self._detected, self._policy
        if source is None or document is None or detected is None or policy is None:
            raise InvariantError("verification needs a processed document")
        try:
            attempt = self._verification.verify(source, output, document, detected, policy)
        finally:
            self.forget()
        return VerificationReport(result=attempt.result, failure=attempt.failure)

    def forget(self) -> None:
        self._source = None
        self._document = None
        self._detected = None
        self._policy = None
