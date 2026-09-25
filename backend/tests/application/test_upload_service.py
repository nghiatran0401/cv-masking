from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest
from service_helpers import ManualClock
from synthetic_files import SYNTHETIC_PDF

from cv_masking.application import JobService, UploadError, UploadService
from cv_masking.config import Settings
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.ids import BatchId
from cv_masking.ports.metadata import RecordNotFoundError


def test_upload_times_out_when_the_clock_advances(
    service: JobService, uploads: UploadService, clock: ManualClock
) -> None:
    batch = service.create_batch()

    def chunks() -> Iterator[bytes]:
        yield SYNTHETIC_PDF[:10]
        clock.advance(timedelta(seconds=Settings().upload_timeout_seconds))
        yield SYNTHETIC_PDF[10:]

    with pytest.raises(UploadError) as caught:
        uploads.upload(
            batch.batch_id, chunks(), filename="synthetic.pdf", content_type="application/pdf"
        )
    assert caught.value.code is ErrorCode.UPLOAD_TIMEOUT
    documents = service.list_documents(batch.batch_id)
    assert len(documents) == 1
    assert documents[0].error_code is ErrorCode.UPLOAD_TIMEOUT


def test_unknown_batch_is_not_found(uploads: UploadService) -> None:
    with pytest.raises(RecordNotFoundError):
        uploads.upload(BatchId(uuid4()), [SYNTHETIC_PDF], filename=None, content_type=None)
