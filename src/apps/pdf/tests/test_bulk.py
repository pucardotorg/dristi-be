"""Bulk generation: chunking, fan-out, merge, partial success, retry, cancel (#11, #12)."""

from unittest.mock import patch

import pytest

from apps.files.models import File
from apps.pdf.exceptions import PDFDependencyError, PDFRequestDataError
from apps.pdf.models import PDFJob, PDFJobRecordStatus, PDFJobStatus
from apps.pdf.renderer.merge import page_count
from apps.pdf.services import bulk, jobs
from apps.pdf.services.documents import read_document
from apps.pdf.tasks import generate_pdf_record
from apps.pdf.tests.conftest import drain
from apps.pdf.tests.factories import bulk_request, make_bulk_template, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return make_user()


def create(user, count, key="bulk-notice"):
    with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
        job, _ = jobs.create_job(
            jobs.JobRequest(key=key, tenant_id="kl", data=bulk_request(count), entity_id="reg-1"),
            user=user,
        )
    return job


def test_plan_chunks():
    assert bulk.plan_chunks(1000, 100) == [(offset, 100) for offset in range(0, 1000, 100)]
    assert bulk.plan_chunks(5, 2) == [(0, 2), (2, 2), (4, 1)]
    assert bulk.plan_chunks(2, 2) == [(0, 2)]


def test_records_must_be_a_non_empty_list():
    config = {"bulk": {"records_path": "$.records"}}
    for data in ({}, {"records": []}, {"records": "x"}):
        with pytest.raises(PDFRequestDataError):
            bulk.extract_records(config, data)


@pytest.mark.parametrize(
    ("count", "chunks"),
    [(1, 1), (2, 1), (5, 3)],  # below, exactly at and above max records per document
)
def test_chunking_and_completion(user, broker, count, chunks):
    make_bulk_template(merge=False)
    job = create(user, count)
    assert job.is_bulk and job.total_count == count

    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert job.records.count() == chunks
    assert job.completed_count == count and job.failed_count == 0
    assert len(job.file_ids) == chunks
    assert all(r.status == PDFJobRecordStatus.COMPLETED for r in job.records.all())


def test_chunks_are_merged_into_one_document(user, broker):
    make_bulk_template(merge=True)
    job = create(user, 5)
    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert len(job.file_ids) == 1
    merged = read_document(job.file_ids[0])
    assert page_count(merged) == 5  # one section (page) per record
    assert File.objects.count() == 4  # three chunks plus the merged document


def test_each_record_sees_its_own_data_and_the_whole_request(user, broker):
    import io

    from pypdf import PdfReader

    make_bulk_template(merge=True)
    job = create(user, 2)
    drain(broker)
    job.refresh_from_db()

    reader = PdfReader(io.BytesIO(read_document(job.file_ids[0])))
    first, second = (page.extract_text() for page in reader.pages)
    assert "Notice 1" in first and "Person 1" in first and "District Court" in first
    assert "Notice 2" in second


def test_parallelism_is_bounded(user, broker, settings):
    settings.PDF_BULK_MAX_PARALLEL_CHUNKS = 2
    make_bulk_template(merge=False)
    job = create(user, 10)

    from apps.pdf.tasks import generate_bulk_pdf

    generate_bulk_pdf.fn(str(job.id), 0)
    statuses = list(job.records.values_list("status", flat=True))
    assert statuses.count(PDFJobRecordStatus.QUEUED) == 2
    assert statuses.count(PDFJobRecordStatus.PENDING) == 3

    drain(broker)
    job.refresh_from_db()
    assert job.status == PDFJobStatus.COMPLETED


def test_failed_chunk_gives_partial_success(user, broker, settings, no_retry_delay):
    settings.PDF_JOB_MAX_RETRIES = 1
    make_bulk_template(merge=True)
    job = create(user, 5)

    real = bulk.render_variables

    def fail_second_chunk(config, contexts):
        if contexts[0]["data"]["number"] == 3:
            raise PDFDependencyError()
        return real(config, contexts)

    with patch("apps.pdf.services.bulk.render_variables", side_effect=fail_second_chunk):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.PARTIAL_SUCCESS
    assert (job.completed_count, job.failed_count) == (3, 2)
    assert job.error_code == "PDF_BULK_PARTIAL"
    failed = job.records.get(sequence=1)
    assert failed.status == PDFJobRecordStatus.FAILED
    assert failed.attempt_count == 2  # retried before giving up
    assert failed.file_id == ""
    # Merge is withheld for a partial job; the successful chunks are returned.
    assert len(job.file_ids) == 2


def test_partial_merge_when_configured(user, broker, settings):
    settings.PDF_JOB_MAX_RETRIES = 0
    make_bulk_template(merge=True, merge_partial=True)
    job = create(user, 5)
    real = bulk.render_variables

    def fail_last(config, contexts):
        if contexts[0]["data"]["number"] == 5:
            raise PDFRequestDataError()
        return real(config, contexts)

    with patch("apps.pdf.services.bulk.render_variables", side_effect=fail_last):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.PARTIAL_SUCCESS
    assert len(job.file_ids) == 1
    assert page_count(read_document(job.file_ids[0])) == 4


def test_every_chunk_failing_fails_the_job(user, broker, settings):
    settings.PDF_JOB_MAX_RETRIES = 0
    make_bulk_template()
    job = create(user, 3)
    with patch("apps.pdf.services.bulk.render_variables", side_effect=PDFRequestDataError()):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_INVALID_REQUEST_DATA"
    assert job.file_ids == []


def test_chunk_retry_does_not_regenerate_other_chunks(user, broker, no_retry_delay):
    make_bulk_template(merge=False)
    job = create(user, 4)
    real = bulk.render_variables
    calls = []

    def flaky(config, contexts):
        calls.append(contexts[0]["data"]["number"])
        if calls.count(3) == 1 and contexts[0]["data"]["number"] == 3:
            raise PDFDependencyError()
        return real(config, contexts)

    with patch("apps.pdf.services.bulk.render_variables", side_effect=flaky):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert sorted(calls) == [1, 3, 3]


def test_duplicate_chunk_delivery_is_ignored(user, broker):
    make_bulk_template(merge=False)
    job = create(user, 2)
    drain(broker)
    generate_pdf_record.fn(str(job.id), 0, 0)
    assert File.objects.count() == 1


def test_cancellation_mid_run_stops_scheduling_and_cleans_up(user, broker, settings):
    settings.PDF_BULK_MAX_PARALLEL_CHUNKS = 1
    make_bulk_template(merge=False)
    job = create(user, 6)
    real = bulk.render_variables
    rendered = []

    def cancel_after_first(config, contexts):
        rendered.append(contexts[0]["data"]["number"])
        content = real(config, contexts)
        if len(rendered) == 2:
            jobs.cancel_job(job.id)
        return content

    with patch("apps.pdf.services.bulk.render_variables", side_effect=cancel_after_first):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.CANCELLED
    assert rendered == [1, 3]  # the third chunk never started
    statuses = dict(job.records.values_list("sequence", "status"))
    assert statuses == {
        0: PDFJobRecordStatus.COMPLETED,
        1: PDFJobRecordStatus.CANCELLED,
        2: PDFJobRecordStatus.CANCELLED,
    }
    # The chunk persisted before cancellation is deleted through apps.files.
    assert File.objects.count() == 0
    assert job.records.get(sequence=0).file_id == ""


def test_bulk_job_counts_records_not_chunks(user, broker):
    make_bulk_template(merge=False)
    job = create(user, 5)
    drain(broker)
    assert bulk.completed_record_count(job.id) == 5
    assert PDFJob.objects.get(pk=job.pk).completed_count == 5
