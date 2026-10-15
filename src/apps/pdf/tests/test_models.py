"""Model tests: versioning, constraints and the job status lifecycle (#2, #3)."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.pdf.exceptions import PDFJobStateError
from apps.pdf.models import PDFJob, PDFJobRecord, PDFJobStatus, PDFTemplate, PDFTemplateVersion
from apps.pdf.tests.factories import DATA_CONFIG, FORMAT_CONFIG, make_template

pytestmark = pytest.mark.django_db


def make_job(version, **overrides):
    defaults = {
        "key": version.template.key,
        "template_version": version,
        "tenant_id": "kl",
        "reuse_key": "x" * 64,
    }
    defaults.update(overrides)
    return PDFJob.objects.create(**defaults)


class TestTemplateVersion:
    def test_versions_are_numbered_and_only_latest_active_stays_active(self):
        first = make_template()
        second = make_template()
        first.refresh_from_db()

        assert (first.version, second.version) == (1, 2)
        assert not first.is_active
        assert second.is_active

    def test_reactivating_an_old_version_deactivates_the_current_one(self):
        first = make_template()
        second = make_template()
        first.refresh_from_db()
        first.is_active = True
        first.save()
        second.refresh_from_db()

        assert first.is_active and not second.is_active

    def test_single_active_version_is_enforced_by_the_database(self):
        version = make_template()
        with pytest.raises(IntegrityError), transaction.atomic():
            PDFTemplateVersion.objects.bulk_create(
                [
                    PDFTemplateVersion(
                        template=version.template,
                        version=2,
                        format_config=FORMAT_CONFIG,
                        is_active=True,
                    )
                ]
            )

    def test_invalid_format_config_is_rejected_on_save(self):
        template = PDFTemplate.objects.create(key="broken", name="Broken")
        with pytest.raises(ValidationError) as excinfo:
            PDFTemplateVersion.objects.create(
                template=template, format_config={"body": [{"type": "nope"}]}
            )
        assert "format_config" in excinfo.value.message_dict

    def test_invalid_data_config_is_rejected_on_save(self):
        template = PDFTemplate.objects.create(key="broken", name="Broken")
        with pytest.raises(ValidationError) as excinfo:
            PDFTemplateVersion.objects.create(
                template=template,
                format_config=FORMAT_CONFIG,
                data_config={"mappings": [{"type": "direct", "target": "x", "path": "$[["}]},
            )
        assert "data_config" in excinfo.value.message_dict

    def test_used_version_configuration_is_immutable(self):
        version = make_template()
        make_job(version)
        version.format_config = {**FORMAT_CONFIG, "page": {"size": "A5"}}
        with pytest.raises(ValidationError):
            version.save()

    def test_unused_version_can_still_be_edited(self):
        version = make_template()
        version.data_config = {**DATA_CONFIG, "sync_render": False}
        version.save()
        version.refresh_from_db()
        assert version.data_config["sync_render"] is False

    def test_used_version_can_still_be_deactivated(self):
        version = make_template()
        make_job(version)
        version.is_active = False
        version.save()
        version.refresh_from_db()
        assert not version.is_active

    def test_template_key_format_is_validated(self):
        template = PDFTemplate(key="Not A Key", name="x")
        with pytest.raises(ValidationError):
            template.full_clean()


class TestJobLifecycle:
    @pytest.fixture
    def job(self):
        return make_job(make_template())

    def test_happy_path_sets_timestamps(self, job):
        job.transition_to(PDFJobStatus.QUEUED)
        assert job.queued_at is not None
        job.transition_to(PDFJobStatus.PROCESSING)
        assert job.started_at is not None
        job.transition_to(PDFJobStatus.COMPLETED)
        assert job.completed_at is not None
        assert job.is_terminal

    @pytest.mark.parametrize(
        "path",
        [
            [PDFJobStatus.COMPLETED],
            [PDFJobStatus.QUEUED, PDFJobStatus.COMPLETED],
            [
                PDFJobStatus.QUEUED,
                PDFJobStatus.PROCESSING,
                PDFJobStatus.COMPLETED,
                PDFJobStatus.FAILED,
            ],
            [PDFJobStatus.CANCELLED, PDFJobStatus.QUEUED],
        ],
    )
    def test_invalid_transitions_raise(self, job, path):
        with pytest.raises(PDFJobStateError):
            for status in path:
                job.transition_to(status)

    @pytest.mark.parametrize("status", [PDFJobStatus.QUEUED, PDFJobStatus.PROCESSING])
    def test_active_jobs_can_be_cancelled(self, job, status):
        job.transition_to(PDFJobStatus.QUEUED)
        if status == PDFJobStatus.PROCESSING:
            job.transition_to(PDFJobStatus.PROCESSING)
        job.transition_to(PDFJobStatus.CANCELLED)
        assert job.status == PDFJobStatus.CANCELLED

    def test_partial_success_requires_a_multi_record_bulk_job(self, job):
        job.transition_to(PDFJobStatus.QUEUED)
        job.transition_to(PDFJobStatus.PROCESSING)
        with pytest.raises(PDFJobStateError):
            job.transition_to(PDFJobStatus.PARTIAL_SUCCESS)

        job.is_bulk, job.total_count = True, 5
        job.transition_to(PDFJobStatus.PARTIAL_SUCCESS)
        assert job.status == PDFJobStatus.PARTIAL_SUCCESS

    def test_partial_success_on_single_job_is_rejected_by_the_database(self):
        version = make_template()
        with pytest.raises(IntegrityError), transaction.atomic():
            make_job(version, status=PDFJobStatus.PARTIAL_SUCCESS, is_bulk=False)


def test_record_sequence_is_unique_per_job():
    job = make_job(make_template(), is_bulk=True, total_count=4)
    PDFJobRecord.objects.create(job=job, sequence=0, count=2)
    with pytest.raises(IntegrityError), transaction.atomic():
        PDFJobRecord.objects.create(job=job, sequence=0, count=2)
