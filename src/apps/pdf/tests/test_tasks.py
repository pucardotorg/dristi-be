"""Single-document generation through the Dramatiq actors (#5, #6, #10).

Integration path: create job -> worker -> apps.files -> COMPLETED, with the
in-memory file storage backend and external services mocked.
"""

from unittest.mock import patch

import pytest
from django.db import OperationalError

from apps.files.models import File, FileType
from apps.files.services import get_file
from apps.pdf.exceptions import PDFDependencyError, PDFRenderError
from apps.pdf.models import PDFJob, PDFJobStatus
from apps.pdf.services import jobs
from apps.pdf.services.documents import read_document
from apps.pdf.tasks import classify, generate_pdf, retry_delay_ms, should_retry
from apps.pdf.tests.conftest import drain
from apps.pdf.tests.factories import REQUEST_DATA, make_template, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return make_user()


@pytest.fixture
def version():
    return make_template()


def create(user, **overrides):
    params = {"key": "case-summons", "tenant_id": "kl", "data": REQUEST_DATA, "entity_id": "case-1"}
    params.update(overrides)
    with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
        job, _ = jobs.create_job(jobs.JobRequest(**params), user=user)
    return job


def test_create_enqueues_the_job_id_only(version, user, broker):
    job = create(user)
    messages = list(broker.queues["pdf"].queue)

    assert job.status == PDFJobStatus.QUEUED
    assert len(messages) == 1
    from dramatiq import Message

    message = Message.decode(messages[0])
    assert message.actor_name == "generate_pdf"
    assert message.args == (str(job.id), 0)


def test_job_completes_with_a_stored_document(version, user, broker):
    job = create(user)
    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert job.completed_count == 1 and job.failed_count == 0
    assert job.started_at and job.completed_at
    assert len(job.file_ids) == 1

    metadata = get_file(job.file_ids[0])
    assert metadata["file_type"] == FileType.PDF
    assert metadata["content_type"] == "application/pdf"
    assert metadata["user_id"] == user.pk
    assert set(metadata["tags"]) == {"pdf", "case-summons", "case-1"}
    assert read_document(job.file_ids[0]).startswith(b"%PDF-")


def test_worker_without_requesting_user_uses_the_system_account(version, broker, settings):
    system = make_user(email="system@dristi.internal")
    settings.FILE_SYSTEM_USER_ID = "system@dristi.internal"
    job = create(None)
    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert get_file(job.file_ids[0])["user_id"] == system.pk


def test_missing_system_account_fails_without_retry(version, broker, settings):
    settings.FILE_SYSTEM_USER_ID = ""
    job = create(None)
    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_INVALID_CONFIG"
    assert job.attempt_count == 1


def test_duplicate_delivery_produces_exactly_one_document(version, user, broker):
    job = create(user)
    generate_pdf.send(str(job.id), 0)  # duplicate of the message create_job sent
    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert File.objects.count() == 1
    assert job.attempt_count == 1


def test_terminal_and_unknown_jobs_are_ignored(version, user, broker):
    job = create(user)
    drain(broker)
    generate_pdf.fn(str(job.id), 1)
    generate_pdf.fn("00000000-0000-0000-0000-000000000000", 0)
    assert File.objects.count() == 1


def test_invalid_request_data_fails_without_retry(version, user, broker):
    job = create(user, data={"name": "no case number"})
    drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_INVALID_REQUEST_DATA"
    assert job.attempt_count == 1
    assert job.file_ids == []
    assert File.objects.count() == 0


def test_dependency_failures_retry_with_backoff_then_fail(
    version, user, broker, settings, no_retry_delay
):
    settings.PDF_JOB_MAX_RETRIES = 2
    job = create(user)
    with patch(
        "apps.pdf.services.generator.build_context", side_effect=PDFDependencyError()
    ) as build:
        drain(broker)
    job.refresh_from_db()

    assert build.call_count == 3
    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_DEPENDENCY_UNAVAILABLE"
    assert job.attempt_count == 3


def test_transient_failure_then_success(version, user, broker, no_retry_delay):
    from apps.pdf.services import generator

    real = generator.build_context
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise PDFDependencyError()
        return real(*args, **kwargs)

    job = create(user)
    with patch("apps.pdf.services.generator.build_context", side_effect=flaky):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.COMPLETED
    assert job.attempt_count == 2


def test_renderer_errors_are_retried_once(version, user, broker, no_retry_delay):
    job = create(user)
    with patch(
        "apps.pdf.services.generator.render_variables", side_effect=PDFRenderError()
    ) as render:
        drain(broker)
    job.refresh_from_db()

    assert render.call_count == 2
    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_RENDER_FAILED"


def test_storage_failure_leaves_no_file_id_and_no_completed_status(
    version, user, broker, settings, no_retry_delay
):
    settings.PDF_JOB_MAX_RETRIES = 1
    job = create(user)
    with patch("apps.pdf.services.documents.upload_file", side_effect=OSError("bucket down")):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_STORAGE_UNAVAILABLE"
    assert job.file_ids == []
    assert "bucket" not in job.error_message
    assert File.objects.count() == 0


def test_cancelled_before_persist_stores_nothing(version, user, broker):
    job = create(user)
    from apps.pdf.services import generator

    real = generator.render_variables

    def render_then_cancel(*args, **kwargs):
        content = real(*args, **kwargs)
        jobs.cancel_job(job.id)
        return content

    with patch("apps.pdf.services.generator.render_variables", side_effect=render_then_cancel):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.CANCELLED
    assert File.objects.count() == 0


def test_cancelled_while_storing_discards_the_upload(version, user, broker):
    job = create(user)
    from apps.pdf.services import documents

    real = documents.upload_file

    def upload_then_cancel(payload):
        result = real(payload)
        PDFJob.objects.filter(pk=job.pk).update(status=PDFJobStatus.CANCELLED)
        return result

    with patch("apps.pdf.services.documents.upload_file", side_effect=upload_then_cancel):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.CANCELLED
    assert job.file_ids == []
    assert File.objects.count() == 0


def test_unexpected_errors_fail_with_a_sanitized_message(version, user, broker):
    job = create(user)
    with patch(
        "apps.pdf.services.generator.build_context",
        side_effect=RuntimeError("token=abc123 secret"),
    ):
        drain(broker)
    job.refresh_from_db()

    assert job.status == PDFJobStatus.FAILED
    assert job.error_code == "PDF_INTERNAL_ERROR"
    assert "abc123" not in job.error_message


def test_structured_logs(version, user, broker, caplog):
    with caplog.at_level("INFO", logger="apps.pdf"):
        job = create(user)
        drain(broker)
    assert f"event=PDF_JOB_CREATED job_id={job.id}" in caplog.text
    assert "event=PDF_JOB_COMPLETED" in caplog.text
    assert f"template_version={job.template_version_id}" in caplog.text


class TestRetryPolicy:
    def test_classification(self):
        assert classify(OperationalError()).retryable
        assert classify(PDFDependencyError()).retryable
        assert not classify(ValueError()).retryable

    def test_bounds(self, settings):
        settings.PDF_JOB_MAX_RETRIES = 2
        assert should_retry(PDFDependencyError(), 1)
        assert not should_retry(PDFDependencyError(), 2)
        assert should_retry(PDFRenderError(), 0)
        assert not should_retry(PDFRenderError(), 1)

    def test_exponential_backoff_is_capped(self, settings):
        settings.PDF_RETRY_DELAY_BASE_SECONDS = 10
        settings.PDF_RETRY_DELAY_MAX_SECONDS = 25
        assert [retry_delay_ms(n) for n in range(3)] == [10_000, 20_000, 25_000]
