"""Service-level ownership checks for job actions."""

from unittest.mock import patch

import pytest

from apps.files.models import File
from apps.pdf.models import PDFJob, PDFJobStatus
from apps.pdf.services import jobs
from apps.pdf.tests.conftest import drain
from apps.pdf.tests.factories import REQUEST_DATA, make_template, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_user()


@pytest.fixture
def job(owner, broker):
    make_template()
    with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
        created, _ = jobs.create_job(
            jobs.JobRequest(key="case-summons", tenant_id="kl", data=REQUEST_DATA), user=owner
        )
    return created


def test_owned_by_returns_only_the_users_jobs(job, owner):
    assert list(PDFJob.objects.owned_by(owner)) == [job]
    assert not PDFJob.objects.owned_by(make_user()).exists()
    assert not PDFJob.objects.owned_by(None).exists()


def test_cancel_by_another_user_is_refused_inside_the_lock(job):
    with pytest.raises(jobs.PDFJobNotFound):
        jobs.cancel_job(job.id, user=make_user())
    job.refresh_from_db()
    assert job.status == PDFJobStatus.QUEUED


def test_cancel_by_owner(job, owner):
    assert jobs.cancel_job(job.id, user=owner).status == PDFJobStatus.CANCELLED


def test_delete_by_another_user_is_refused_before_anything_is_deleted(job, broker):
    drain(broker)
    job.refresh_from_db()
    with pytest.raises(jobs.PDFJobNotFound):
        jobs.delete_job_documents(job, user=make_user())
    assert File.objects.count() == 1


def test_in_process_callers_without_a_user_are_not_limited(job):
    assert jobs.cancel_job(job.id).status == PDFJobStatus.CANCELLED
