"""Validate an uploaded PDF and extract a transient text model."""

import logging

from cv_masking.application.jobs import JobService
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentAlert
from cv_masking.domain.ids import DocumentId
from cv_masking.ports.extraction import DocumentExtractor, ExtractedDocument
from cv_masking.ports.storage import ObjectStore, StorageError

logger = logging.getLogger("cv_masking.validation")


class ValidationOutcome:
    __slots__ = ("alerts", "extracted", "job")

    def __init__(
        self,
        job: DocumentJob,
        extracted: ExtractedDocument | None,
        alerts: tuple[HiddenContentAlert, ...],
    ) -> None:
        self.job = job
        self.extracted = extracted
        self.alerts = alerts


class ValidationService:
    __slots__ = ("_extractor", "_inputs", "_jobs")

    def __init__(self, jobs: JobService, inputs: ObjectStore, extractor: DocumentExtractor) -> None:
        self._jobs = jobs
        self._inputs = inputs
        self._extractor = extractor

    def validate(self, document_id: DocumentId) -> ValidationOutcome:
        """UPLOADED PDF → QUEUED, REVIEW_REQUIRED, or FAILED. Text is never stored."""
        job = self._jobs.get_document(document_id)
        if job.document_format is not DocumentFormat.PDF:
            raise InvariantError("PDF validation cannot run on this document format")
        if job.input_ref is None or job.state is not DocumentState.UPLOADED:
            raise InvariantError("PDF validation needs an uploaded document")
        self._jobs.apply(document_id, lambda current, at: current.start_validation(at))
        try:
            with self._inputs.open(job.input_ref, DocumentFormat.PDF) as handle:
                data = handle.read()
        except StorageError as error:
            code = error.code
            failed = self._jobs.apply(document_id, lambda current, at: current.fail(code, at))
            logger.info("document %s validation failed", document_id)
            return ValidationOutcome(failed, None, ())
        result = self._extractor.extract(data)
        if result.failure is not None:
            code = result.failure
            failed = self._jobs.apply(document_id, lambda current, at: current.fail(code, at))
            logger.info("document %s validation failed", document_id)
            return ValidationOutcome(failed, None, ())
        if result.review:
            reviewed = self._jobs.apply(
                document_id,
                lambda current, at: current.validation_needs_review(result.review, at),
            )
            logger.info("document %s validation review hidden=%d", document_id, len(result.alerts))
            return ValidationOutcome(reviewed, None, result.alerts)
        extracted = result.document
        if extracted is None:
            failed = self._jobs.apply(
                document_id, lambda current, at: current.fail(ErrorCode.INTERNAL_ERROR, at)
            )
            logger.info("document %s validation failed", document_id)
            return ValidationOutcome(failed, None, ())
        queued = self._jobs.apply(document_id, lambda current, at: current.validation_passed(at))
        logger.info("document %s validation passed pages=%d", document_id, len(extracted.parts))
        return ValidationOutcome(queued, extracted, ())
