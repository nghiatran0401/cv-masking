"""Download one allowlisted CV URL and store it through the normal upload path.

The URL is not logged or stored. A network failure becomes ``UPLOAD_SOURCE_UNAVAILABLE``
and leaves no document row.
"""

import logging

from cv_masking.application.uploads import UploadError, UploadService
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob
from cv_masking.domain.ids import BatchId
from cv_masking.domain.source_url import parse_cv_source_url
from cv_masking.ports.cv_source import CvSource, CvSourceError

logger = logging.getLogger("cv_masking.source_import")


class SourceImportService:
    __slots__ = ("_max_file_bytes", "_source", "_uploads")

    def __init__(self, uploads: UploadService, source: CvSource, *, max_file_bytes: int) -> None:
        self._uploads = uploads
        self._source = source
        self._max_file_bytes = max_file_bytes

    def import_url(self, batch_id: BatchId, raw_url: str) -> DocumentJob:
        parsed = parse_cv_source_url(raw_url)
        if parsed is None:
            raise UploadError(ErrorCode.UPLOAD_MALFORMED_REQUEST, batch_id=str(batch_id))
        try:
            data = self._source.fetch(parsed.href, max_bytes=self._max_file_bytes)
        except CvSourceError:
            logger.info(
                "batch %s source import refused code=%s",
                batch_id,
                ErrorCode.UPLOAD_SOURCE_UNAVAILABLE.value,
            )
            raise UploadError(ErrorCode.UPLOAD_SOURCE_UNAVAILABLE, batch_id=str(batch_id)) from None
        if len(data) > self._max_file_bytes:
            raise UploadError(
                ErrorCode.UPLOAD_FILE_TOO_LARGE,
                limit=self._max_file_bytes,
                batch_id=str(batch_id),
            )
        return self._uploads.upload(
            batch_id,
            [data],
            filename=parsed.filename,
            content_type=None,
        )
