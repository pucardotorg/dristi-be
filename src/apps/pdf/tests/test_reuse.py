"""Reuse-key computation and stale detection (#7)."""

import pytest

from apps.pdf.models import PDFJob, PDFJobStatus
from apps.pdf.services.reuse import compute_reuse_key, find_reusable_job
from apps.pdf.tests.factories import make_template

BASE = {
    "tenant_id": "kl",
    "key": "case-summons",
    "entity_id": "case-1",
    "version": 1,
    "data_config": {"significant_fields": ["$.case.number"]},
    "request_data": {"case": {"number": "1"}, "requested_at": "2026-01-01"},
}


def key(**overrides):
    return compute_reuse_key(**{**BASE, **overrides})


def test_key_is_deterministic_and_order_insensitive():
    reordered = {"requested_at": "2026-01-01", "case": {"number": "1"}}
    assert key() == key(request_data=reordered)
    assert len(key()) == 64


def test_volatile_fields_outside_significant_fields_are_ignored():
    assert key() == key(request_data={"case": {"number": "1"}, "requested_at": "2027-05-05"})


def test_significant_fields_change_the_key():
    assert key() != key(request_data={"case": {"number": "2"}})


@pytest.mark.parametrize(
    "override",
    [{"version": 2}, {"tenant_id": "dl"}, {"key": "other"}, {"entity_id": "case-2"}],
)
def test_identity_fields_and_version_change_the_key(override):
    assert key() != key(**override)


def test_without_significant_fields_the_whole_request_counts():
    assert key(data_config={}) != key(
        data_config={}, request_data={**BASE["request_data"], "requested_at": "x"}
    )


@pytest.mark.django_db
class TestFindReusableJob:
    @pytest.fixture
    def version(self):
        return make_template()

    def make(self, version, status, **extra):
        return PDFJob.objects.create(
            key="case-summons",
            template_version=version,
            tenant_id="kl",
            reuse_key="r" * 64,
            status=status,
            **extra,
        )

    def test_completed_job_is_reused(self, version):
        job = self.make(version, PDFJobStatus.COMPLETED, file_ids=["f"])
        assert find_reusable_job("r" * 64) == job

    @pytest.mark.parametrize(
        "status",
        [PDFJobStatus.FAILED, PDFJobStatus.CANCELLED, PDFJobStatus.QUEUED, PDFJobStatus.PROCESSING],
    )
    def test_other_statuses_are_not_reused(self, version, status):
        self.make(version, status)
        assert find_reusable_job("r" * 64) is None

    def test_partial_success_is_not_reused(self, version):
        self.make(version, PDFJobStatus.PARTIAL_SUCCESS, is_bulk=True, total_count=3)
        assert find_reusable_job("r" * 64) is None

    def test_jobs_with_deleted_documents_are_not_reused(self, version):
        from django.utils import timezone

        self.make(version, PDFJobStatus.COMPLETED, files_deleted_at=timezone.now())
        assert find_reusable_job("r" * 64) is None
