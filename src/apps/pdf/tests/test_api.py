"""API tests for /api/v1/pdf/... (#4, #13)."""

from datetime import datetime
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.files.models import File
from apps.pdf.models import PDFJob, PDFJobStatus
from apps.pdf.tests.conftest import drain
from apps.pdf.tests.factories import (
    DATA_CONFIG,
    REQUEST_DATA,
    bulk_request,
    make_bulk_template,
    make_template,
    make_user,
)
from apps.users.models import RegistrationStatus

pytestmark = pytest.mark.django_db

JOBS = "pdf-job-list"


def detail(name, job):
    return reverse(f"pdf-job-{name}", kwargs={"id": str(job.id)})


@pytest.fixture
def user():
    return make_user()


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def version():
    return make_template()


@pytest.fixture(autouse=True)
def run_on_commit():
    with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
        yield


def assert_meta(payload):
    meta = payload["meta"]
    assert meta["spec_version"] == "1.0"
    assert "app_version" in meta
    assert datetime.fromisoformat(meta["timestamp"]).utcoffset().total_seconds() == 19800


def create(client, **overrides):
    body = {"key": "case-summons", "tenant_id": "kl", "entity_id": "case-1", "data": REQUEST_DATA}
    body.update(overrides)
    return client.post(reverse(JOBS), body, format="json")


def completed_job(client, broker):
    response = create(client)
    drain(broker)
    return PDFJob.objects.get(pk=response.json()["id"])


class TestCreate:
    def test_creates_and_queues_a_job(self, client, version, broker, user):
        response = create(client)

        assert response.status_code == 202
        body = response.json()
        assert_meta(body)
        assert body["status"] == "QUEUED"
        assert body["key"] == "case-summons"
        assert body["tenant_id"] == "kl" and body["entity_id"] == "case-1"
        assert body["file_ids"] == [] and body["total_count"] == 1
        assert body["reused"] is False and body["completed_at"] is None
        assert body["template_version"] == 1
        job = PDFJob.objects.get(pk=body["id"])
        assert job.requested_by == user and job.created_by == user

    def test_reuses_a_completed_job(self, client, version, broker):
        first = completed_job(client, broker)
        changed_volatile = {**REQUEST_DATA, "requested_at": "2030-01-01T00:00:00Z"}
        response = create(client, data=changed_volatile)

        assert response.status_code == 200
        assert response.json()["id"] == str(first.id)
        assert response.json()["reused"] is True
        assert response.json()["file_ids"] == first.file_ids
        assert PDFJob.objects.count() == 1

    def test_force_regenerate_creates_a_new_job(self, client, version, broker):
        completed_job(client, broker)
        response = create(client, force_regenerate=True)
        assert response.status_code == 202
        assert PDFJob.objects.count() == 2

    def test_new_template_version_makes_old_documents_stale(self, client, version, broker):
        completed_job(client, broker)
        make_template(data_config=DATA_CONFIG)
        response = create(client)
        assert response.status_code == 202
        assert response.json()["template_version"] == 2

    def test_unknown_key_is_404(self, client):
        response = create(client, key="missing")
        assert response.status_code == 404
        assert response.json()["code"] == "PDF_TEMPLATE_NOT_FOUND"
        assert_meta(response.json())

    @pytest.mark.parametrize(
        "body",
        [
            {"tenant_id": "kl", "data": {}},
            {"key": "case-summons", "data": {}},
            {"key": "case-summons", "tenant_id": "kl", "data": ["not", "an", "object"]},
            {"key": "case-summons", "tenant_id": "kl"},
        ],
    )
    def test_invalid_payload_is_400(self, client, version, body):
        response = client.post(reverse(JOBS), body, format="json")
        assert response.status_code == 400
        assert PDFJob.objects.count() == 0

    def test_oversized_data_is_rejected(self, client, version, settings):
        settings.PDF_MAX_REQUEST_DATA_BYTES = 50
        response = create(client, data={"blob": "x" * 100})
        assert response.status_code == 400

    def test_request_schema_rejects_bad_data_before_a_job_exists(self, client):
        make_template(
            data_config={**DATA_CONFIG, "request_schema": {"required": ["case"]}},
        )
        response = create(client, data={"name": "x"})
        assert response.status_code == 400
        assert response.json()["code"] == "PDF_INVALID_REQUEST_DATA"
        assert PDFJob.objects.count() == 0

    def test_bulk_job(self, client, broker):
        make_bulk_template()
        response = create(client, key="bulk-notice", data=bulk_request(5))
        assert response.status_code == 202
        assert response.json()["is_bulk"] is True
        assert response.json()["total_count"] == 5

    def test_authorization_header_is_not_persisted(self, client, version):
        response = client.post(
            reverse(JOBS),
            {"key": "case-summons", "tenant_id": "kl", "data": REQUEST_DATA},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
            HTTP_X_CORRELATION_ID="corr-42",
        )
        job = PDFJob.objects.get(pk=response.json()["id"])
        assert "secret-token" not in str(job.request_data)
        assert job.correlation_id == "corr-42"


class TestSearchAndRetrieve:
    def test_list_is_paginated_newest_first_and_filterable(self, client, version, broker):
        create(client, entity_id="case-1")
        create(client, entity_id="case-2")
        create(client, entity_id="case-2", data={**REQUEST_DATA, "name": "Other"})

        response = client.get(reverse(JOBS), {"entity_id": "case-2"})
        body = response.json()
        assert response.status_code == 200
        assert_meta(body)
        assert body["count"] == 2
        assert {"next", "previous", "results"} <= set(body)
        created = [job["created_at"] for job in body["results"]]
        assert created == sorted(created, reverse=True)

        assert client.get(reverse(JOBS), {"key": "missing"}).json()["count"] == 0
        assert client.get(reverse(JOBS), {"status": "QUEUED"}).json()["count"] == 3
        assert client.get(reverse(JOBS), {"tenant_id": "kl"}).json()["count"] == 3

    def test_invalid_filter_is_400(self, client, version):
        assert client.get(reverse(JOBS), {"status": "DONE"}).status_code == 400

    def test_pagination(self, client, version):
        for index in range(21):
            create(client, entity_id=f"case-{index}")
        first = client.get(reverse(JOBS)).json()
        assert first["count"] == 21 and len(first["results"]) == 20
        assert first["next"] is not None
        second = client.get(reverse(JOBS), {"page": 2}).json()
        assert len(second["results"]) == 1 and second["next"] is None
        assert client.get(reverse(JOBS), {"page": 3}).status_code == 404

    def test_retrieve(self, client, version, broker):
        job = completed_job(client, broker)
        response = client.get(detail("detail", job))
        assert response.status_code == 200
        assert_meta(response.json())
        assert response.json()["status"] == "COMPLETED"
        assert response.json()["file_ids"] == job.file_ids

    def test_retrieve_bulk_includes_chunks(self, client, broker):
        make_bulk_template(merge=False)
        response = create(client, key="bulk-notice", data=bulk_request(3))
        drain(broker)
        body = client.get(reverse("pdf-job-detail", kwargs={"id": response.json()["id"]})).json()
        assert [record["sequence"] for record in body["records"]] == [0, 1]
        assert body["records"][0]["status"] == "COMPLETED"

    def test_users_only_see_their_own_jobs(self, client, version, broker):
        job = completed_job(client, broker)
        other = APIClient()
        other.force_authenticate(user=make_user())

        assert other.get(reverse(JOBS)).json()["count"] == 0
        assert other.get(detail("detail", job)).status_code == 404
        assert other.get(detail("download", job)).status_code == 404
        assert other.post(detail("cancel", job)).status_code == 404
        assert other.delete(detail("detail", job)).status_code == 404

    def test_staff_see_every_job(self, client, version, broker):
        completed_job(client, broker)
        staff = APIClient()
        staff.force_authenticate(user=make_user(is_staff=True))
        assert staff.get(reverse(JOBS)).json()["count"] == 1


class TestCancel:
    def test_cancel_queued_job(self, client, version):
        job = PDFJob.objects.get(pk=create(client).json()["id"])
        response = client.post(detail("cancel", job))
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
        assert_meta(response.json())

    def test_cancel_terminal_job_conflicts(self, client, version, broker):
        job = completed_job(client, broker)
        response = client.post(detail("cancel", job))
        assert response.status_code == 409
        assert response.json()["code"] == "PDF_INVALID_TRANSITION"

    def test_cancelled_job_is_never_processed(self, client, version, broker):
        job = PDFJob.objects.get(pk=create(client).json()["id"])
        client.post(detail("cancel", job))
        drain(broker)
        job.refresh_from_db()
        assert job.status == PDFJobStatus.CANCELLED
        assert File.objects.count() == 0


class TestDownloadAndDelete:
    def test_download_streams_the_pdf(self, client, version, broker):
        job = completed_job(client, broker)
        response = client.get(detail("download", job))

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert 'filename="case-summons-case-1.pdf"' in response["Content-Disposition"]
        assert b"".join(response.streaming_content).startswith(b"%PDF-")

    def test_download_bulk_chunk_by_sequence(self, client, broker):
        make_bulk_template(merge=False)
        job_id = create(client, key="bulk-notice", data=bulk_request(3)).json()["id"]
        drain(broker)
        url = reverse("pdf-job-download", kwargs={"id": job_id})

        response = client.get(url, {"sequence": 1})
        assert response.status_code == 200
        assert "part-2" in response["Content-Disposition"]
        assert client.get(url, {"sequence": 9}).status_code == 404
        assert client.get(url, {"sequence": 1, "index": 0}).status_code == 400

    def test_download_without_documents_is_404(self, client, version):
        job = PDFJob.objects.get(pk=create(client).json()["id"])
        response = client.get(detail("download", job))
        assert response.status_code == 404
        assert response.json()["code"] == "PDF_NO_DOCUMENT"

    def test_delete_removes_documents_through_apps_files(self, client, version, broker):
        job = completed_job(client, broker)
        assert File.objects.count() == 1

        response = client.delete(detail("detail", job))
        assert response.status_code == 200
        body = response.json()
        assert body["file_ids"] == [] and body["files_deleted_at"] is not None
        assert_meta(body)
        assert File.objects.count() == 0
        assert client.get(detail("download", job)).status_code == 404
        # A job whose documents were deleted is never reused.
        assert create(client).status_code == 202

    def test_delete_active_job_conflicts(self, client, version):
        job = PDFJob.objects.get(pk=create(client).json()["id"])
        assert client.delete(detail("detail", job)).status_code == 409

    def test_partial_storage_delete_failure_keeps_remaining_ids(self, client, version, broker):
        job = completed_job(client, broker)
        with patch("apps.pdf.services.documents.delete_file", side_effect=OSError("down")):
            response = client.delete(detail("detail", job))
        assert response.status_code == 409
        job.refresh_from_db()
        assert len(job.file_ids) == 1 and job.files_deleted_at is None


class TestSyncRender:
    url = "pdf-render"

    def test_returns_pdf_bytes_and_stores_nothing(self, client, version):
        response = client.post(
            reverse(self.url),
            {"key": "case-summons", "tenant_id": "kl", "data": REQUEST_DATA},
            format="json",
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")
        assert PDFJob.objects.count() == 0
        assert File.objects.count() == 0

    def test_bulk_templates_are_rejected(self, client):
        make_bulk_template()
        response = client.post(
            reverse(self.url),
            {"key": "bulk-notice", "tenant_id": "kl", "data": bulk_request(2)},
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "PDF_SYNC_RENDER_NOT_ALLOWED"

    def test_external_api_templates_are_rejected(self, client):
        make_template(
            "with-api",
            data_config={
                "mappings": [{"type": "external_api", "target": "x", "url": "https://api.example/"}]
            },
            format_config={"body": [{"type": "paragraph", "text": "{{ x }}"}]},
        )
        response = client.post(
            reverse(self.url), {"key": "with-api", "tenant_id": "kl", "data": {}}, format="json"
        )
        assert response.status_code == 400

    def test_opt_out_flag_is_honoured(self, client):
        make_template("no-sync", data_config={**DATA_CONFIG, "sync_render": False})
        response = client.post(
            reverse(self.url),
            {"key": "no-sync", "tenant_id": "kl", "data": REQUEST_DATA},
            format="json",
        )
        assert response.status_code == 400

    def test_invalid_data_is_400(self, client, version):
        response = client.post(
            reverse(self.url), {"key": "case-summons", "tenant_id": "kl", "data": {}}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["code"] == "PDF_INVALID_REQUEST_DATA"

    def test_hard_timeout(self, client, version, settings):
        import time

        settings.PDF_SYNC_RENDER_TIMEOUT_SECONDS = 1

        def slow(*args, **kwargs):
            time.sleep(2)
            return b"%PDF-late"

        with patch("apps.pdf.services.jobs.render_document", side_effect=slow):
            response = client.post(
                reverse(self.url),
                {"key": "case-summons", "tenant_id": "kl", "data": REQUEST_DATA},
                format="json",
            )
        assert response.status_code == 504
        assert response.json()["code"] == "PDF_SYNC_RENDER_TIMEOUT"


class TestAuthentication:
    @pytest.mark.parametrize(
        ("method", "name"), [("get", JOBS), ("post", JOBS), ("post", "pdf-render")]
    )
    def test_anonymous_requests_are_rejected(self, version, method, name):
        response = getattr(APIClient(), method)(reverse(name), {}, format="json")
        assert response.status_code in (401, 403)

    def test_unregistered_users_are_rejected(self, version):
        api = APIClient()
        api.force_authenticate(
            user=make_user(registration_status=RegistrationStatus.PENDING_PROFILE)
        )
        assert create(api).status_code == 403


def test_schema_tags_pdf_operations(client):
    import json

    response = client.get(f"{reverse('api-schema')}?format=json")
    schema = json.loads(response.content)
    paths = {path: ops for path, ops in schema["paths"].items() if path.startswith("/api/v1/pdf/")}
    assert {
        "/api/v1/pdf/jobs/",
        "/api/v1/pdf/jobs/{id}/",
        "/api/v1/pdf/jobs/{id}/cancel/",
        "/api/v1/pdf/jobs/{id}/download/",
        "/api/v1/pdf/render/",
    } <= set(paths)
    for operations in paths.values():
        for operation in operations.values():
            assert operation["tags"] == ["pdf"]
