"""Concurrent callers never both win a version race."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from service_helpers import uploaded_document

from cv_masking.adapters.local_storage import LocalInputStore
from cv_masking.application import JobService
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.ports.metadata import ConcurrentUpdateError

WORKERS = 8


def test_exactly_one_writer_wins_a_version_race(
    service: JobService, input_store: LocalInputStore
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id)
    barrier = Barrier(WORKERS)

    def cancel(_: int) -> DocumentJob | ConcurrentUpdateError:
        barrier.wait()
        try:
            return service.cancel_document(job.document_id, expected_version=job.version)
        except ConcurrentUpdateError as error:
            return error

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(cancel, range(WORKERS)))
    assert sum(isinstance(r, DocumentJob) for r in results) == 1
    assert sum(isinstance(r, ConcurrentUpdateError) for r in results) == WORKERS - 1
    stored = service.get_document(job.document_id)
    assert stored.state is DocumentState.CANCELLED
    assert stored.version == job.version + 1
