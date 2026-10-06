"""API tests for the submitter and approver endpoints."""

import json

import pytest
from django.urls import reverse

from apps.dristi_requests import services
from apps.dristi_requests.models import Request, RequestApproval


def create_url():
    """Return the generic request create/list URL."""
    return reverse("request-list")


def detail_url(request_id):
    """Return the request detail URL."""
    return reverse("request-detail", args=[request_id])


@pytest.mark.django_db
class TestRequestCreateAPI:
    """POST /requests/."""

    def test_create_request(self, auth_client, simple_type, requester, approver_one):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {"request_type": "SIMPLE", "attributes": json.dumps({"reason": "need it"})},
            format="multipart",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["request_type"] == "SIMPLE"
        assert body["data"] == {"reason": "need it"}
        assert len(body["approvals"]) == 1
        assert body["approvals"][0]["approver"]["email"] == approver_one.email

    def test_create_requires_authentication(self, api_client, simple_type):
        response = api_client.post(
            create_url(),
            {"request_type": "SIMPLE", "attributes": "{}"},
            format="multipart",
        )

        assert response.status_code in (401, 403)

    def test_schema_validation_error(self, auth_client, simple_type, requester, approver_one):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {"request_type": "SIMPLE", "attributes": json.dumps({})},
            format="multipart",
        )

        assert response.status_code == 400
        assert "attributes" in response.json()
        assert Request.objects.count() == 0

    def test_invalid_json_attributes(self, auth_client, simple_type, requester):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {"request_type": "SIMPLE", "attributes": "{not json"},
            format="multipart",
        )

        assert response.status_code == 400
        assert "valid JSON object" in json.dumps(response.json())

    def test_non_object_json_attributes(self, auth_client, simple_type, requester):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {"request_type": "SIMPLE", "attributes": "[1, 2]"},
            format="multipart",
        )

        assert response.status_code == 400

    def test_unknown_request_type(self, auth_client, requester):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {"request_type": "NOPE", "attributes": "{}"},
            format="multipart",
        )

        assert response.status_code == 400

    def test_inactive_request_type_is_rejected(self, auth_client, simple_type, requester):
        simple_type.is_active = False
        simple_type.save()
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {"request_type": "SIMPLE", "attributes": json.dumps({"reason": "x"})},
            format="multipart",
        )

        assert response.status_code == 400

    def test_min_documents_enforced(self, auth_client, lawyer_bar_type, requester, bar_approver):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {
                "request_type": "LAWYER_BAR_UPDATE",
                "attributes": json.dumps({"name": "Jane", "bar_number": "KAR/1"}),
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert "documents" in response.json()
        assert Request.objects.count() == 0

    def test_documents_are_uploaded(
        self, auth_client, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        client = auth_client(requester)

        response = client.post(
            create_url(),
            {
                "request_type": "LAWYER_BAR_UPDATE",
                "attributes": json.dumps({"name": "Jane", "bar_number": "KAR/1"}),
                "documents": [pdf_file("cert.pdf")],
            },
            format="multipart",
        )

        assert response.status_code == 201
        documents = response.json()["documents"]
        assert len(documents) == 1
        assert documents[0]["filename"] == "cert.pdf"
        assert documents[0]["uploaded_by"]["email"] == requester.email
        assert documents[0]["download_url"].endswith(
            f"/api/v1/dristi-requests/{response.json()['id']}/documents/{documents[0]['id']}/"
        )


@pytest.mark.django_db
class TestRequestReadAPI:
    """GET /requests/ and /requests/{id}/."""

    def test_list_returns_only_own_requests(
        self, auth_client, simple_type, requester, outsider, approver_one
    ):
        mine = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "mine"}
        )
        services.create_request(
            request_type=simple_type, requester=outsider, data={"reason": "theirs"}
        )

        response = auth_client(requester).get(create_url())

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["results"][0]["id"] == str(mine.pk)

    def test_staff_sees_all_requests(
        self, auth_client, simple_type, requester, staff_user, approver_one
    ):
        services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "mine"}
        )

        response = auth_client(staff_user).get(create_url())

        assert response.json()["count"] == 1

    def test_retrieve_own_request(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(requester).get(detail_url(request.pk))

        assert response.status_code == 200
        assert response.json()["id"] == str(request.pk)

    def test_retrieve_other_request_is_not_found(
        self, auth_client, simple_type, requester, outsider, approver_one
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(outsider).get(detail_url(request.pk))

        assert response.status_code == 404

    def test_approval_trail(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(requester).get(reverse("request-approvals", args=[request.pk]))

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["status"] == "pending"

    def test_responses_include_meta_envelope(
        self, auth_client, simple_type, requester, approver_one
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        for url in (create_url(), detail_url(request.pk)):
            meta = auth_client(requester).get(url).json()["meta"]
            assert set(meta) == {"timestamp", "app_version", "spec_version"}
            assert meta["spec_version"] == "1.0"

    def test_list_is_paginated(self, auth_client, simple_type, requester, approver_one):
        for index in range(3):
            services.create_request(
                request_type=simple_type, requester=requester, data={"reason": str(index)}
            )

        body = auth_client(requester).get(create_url()).json()

        assert body["count"] == 3
        assert set(body) >= {"count", "next", "previous", "results", "meta"}

    def test_request_types_endpoint(self, auth_client, requester, simple_type):
        response = auth_client(requester).get(reverse("request-type-list"))

        assert response.status_code == 200
        codes = [item["code"] for item in response.json()["results"]]
        assert "SIMPLE" in codes
        assert "LAWYER_BAR_UPDATE" in codes

    def test_request_types_requires_authentication(self, api_client):
        response = api_client.get(reverse("request-type-list"))

        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestApproverAPI:
    """GET /approvals/ and POST /approvals/{id}/decide/."""

    def test_pending_queue_lists_only_own_pending(
        self, auth_client, two_step_type, requester, approver_one, approver_two
    ):
        services.create_request(request_type=two_step_type, requester=requester, data={"amount": 1})

        mine = auth_client(approver_one).get(reverse("request-approval-list")).json()
        theirs = auth_client(approver_two).get(reverse("request-approval-list")).json()

        assert mine["count"] == 1
        assert theirs["count"] == 0

    def test_history_filter_by_status(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        client = auth_client(approver_one)
        pending = client.get(reverse("request-approval-list")).json()
        history = client.get(
            reverse("request-approval-list"), {"status": ["approved", "rejected"]}
        ).json()

        assert pending["count"] == 0
        assert history["count"] == 1

    def test_retrieve_approval_embeds_request(
        self, auth_client, simple_type, requester, approver_one, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file()],
        )
        approval = request.current_approval

        response = auth_client(approver_one).get(
            reverse("request-approval-detail", args=[approval.pk])
        )

        assert response.status_code == 200
        body = response.json()
        assert body["request"]["data"] == {"reason": "x"}
        assert len(body["request"]["documents"]) == 1

    def test_decide_approve_final(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        approval = request.current_approval

        response = auth_client(approver_one).post(
            reverse("request-approval-decide", args=[approval.pk]),
            {"decision": "approved", "comments": "looks good"},
            format="json",
        )

        request.refresh_from_db()
        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        assert request.status == Request.Status.APPROVED

    def test_decide_approve_moves_to_next_step(
        self, auth_client, two_step_type, requester, approver_one, approver_two
    ):
        request = services.create_request(
            request_type=two_step_type, requester=requester, data={"amount": 1}
        )

        response = auth_client(approver_one).post(
            reverse("request-approval-decide", args=[request.current_approval.pk]),
            {"decision": "approved"},
            format="json",
        )
        request.refresh_from_db()

        assert response.status_code == 200
        assert request.status == Request.Status.PENDING
        assert request.current_approval.approver == approver_two

    def test_decide_reject(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(approver_one).post(
            reverse("request-approval-decide", args=[request.current_approval.pk]),
            {"decision": "rejected", "comments": "nope"},
            format="json",
        )
        request.refresh_from_db()

        assert response.status_code == 200
        assert request.status == Request.Status.REJECTED

    def test_other_user_cannot_decide(
        self, auth_client, simple_type, requester, approver_one, approver_two
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(approver_two).post(
            reverse("request-approval-decide", args=[request.current_approval.pk]),
            {"decision": "approved"},
            format="json",
        )
        request.refresh_from_db()

        assert response.status_code == 404
        assert request.status == Request.Status.PENDING

    def test_requester_cannot_decide(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(requester).post(
            reverse("request-approval-decide", args=[request.current_approval.pk]),
            {"decision": "approved"},
            format="json",
        )

        assert response.status_code == 404

    def test_invalid_decision_value(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(approver_one).post(
            reverse("request-approval-decide", args=[request.current_approval.pk]),
            {"decision": "maybe"},
            format="json",
        )

        assert response.status_code == 400

    def test_cannot_decide_twice(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        url = reverse("request-approval-decide", args=[request.current_approval.pk])
        client = auth_client(approver_one)
        client.post(url, {"decision": "approved"}, format="json")

        response = client.post(url, {"decision": "rejected"}, format="json")

        assert response.status_code == 400

    def test_decide_requires_authentication(self, api_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = api_client.post(
            reverse("request-approval-decide", args=[request.current_approval.pk]),
            {"decision": "approved"},
            format="json",
        )

        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestResubmitAndCancelAPI:
    """POST /requests/{id}/resubmit/ and /cancel/."""

    def test_resubmit_rejected_request(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "rejected", actor=approver_one)

        response = auth_client(requester).post(reverse("request-resubmit", args=[request.pk]))
        request.refresh_from_db()

        assert response.status_code == 200
        assert response.json()["version"] == 2
        assert request.status == Request.Status.PENDING
        assert request.approvals.filter(status=RequestApproval.Status.PENDING).count() == 1

    def test_cannot_resubmit_pending(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(requester).post(reverse("request-resubmit", args=[request.pk]))

        assert response.status_code == 400

    def test_other_user_cannot_resubmit(
        self, auth_client, simple_type, requester, outsider, approver_one
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "rejected", actor=approver_one)

        response = auth_client(outsider).post(reverse("request-resubmit", args=[request.pk]))

        assert response.status_code == 404

    def test_approver_cannot_cancel_someone_elses_request(
        self, auth_client, simple_type, requester, approver_one
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(approver_one).post(reverse("request-cancel", args=[request.pk]))
        request.refresh_from_db()

        assert response.status_code == 404
        assert request.status == Request.Status.PENDING

    def test_cancel_pending_request(self, auth_client, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        response = auth_client(requester).post(reverse("request-cancel", args=[request.pk]))
        request.refresh_from_db()

        assert response.status_code == 200
        assert request.status == Request.Status.CANCELLED

    def test_cancelled_request_cannot_be_decided(
        self, auth_client, simple_type, requester, approver_one
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        approval = request.current_approval
        auth_client(requester).post(reverse("request-cancel", args=[request.pk]))

        response = auth_client(approver_one).post(
            reverse("request-approval-decide", args=[approval.pk]),
            {"decision": "approved"},
            format="json",
        )

        assert response.status_code == 400

    def test_cannot_cancel_approved_request(
        self, auth_client, simple_type, requester, approver_one
    ):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        response = auth_client(requester).post(reverse("request-cancel", args=[request.pk]))

        assert response.status_code == 400


@pytest.mark.django_db
class TestDocumentDownloadAPI:
    """GET /requests/{request_id}/documents/{document_id}/."""

    @pytest.fixture
    def request_with_document(self, simple_type, requester, approver_one, pdf_file):
        return services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file("cert.pdf")],
        )

    def _url(self, request, document):
        return reverse("request-document-download", args=[request.pk, document.pk])

    def test_requester_can_download(self, auth_client, request_with_document, requester):
        document = request_with_document.documents.first()

        response = auth_client(requester).get(self._url(request_with_document, document))

        assert response.status_code == 200
        assert response["Content-Disposition"].startswith("attachment")
        assert b"".join(response.streaming_content) == b"%PDF-1.4 fake"

    def test_approver_on_trail_can_download(self, auth_client, request_with_document, approver_one):
        document = request_with_document.documents.first()

        response = auth_client(approver_one).get(self._url(request_with_document, document))

        assert response.status_code == 200

    def test_staff_can_download(self, auth_client, request_with_document, staff_user):
        document = request_with_document.documents.first()

        response = auth_client(staff_user).get(self._url(request_with_document, document))

        assert response.status_code == 200

    def test_unauthorized_user_gets_404(self, auth_client, request_with_document, outsider):
        document = request_with_document.documents.first()

        response = auth_client(outsider).get(self._url(request_with_document, document))

        assert response.status_code == 404

    def test_anonymous_user_is_rejected(self, api_client, request_with_document):
        document = request_with_document.documents.first()

        response = api_client.get(self._url(request_with_document, document))

        assert response.status_code in (401, 403)

    def test_mismatched_request_id_gets_404(
        self, auth_client, request_with_document, simple_type, requester, approver_one
    ):
        other = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "other"}
        )
        document = request_with_document.documents.first()

        response = auth_client(requester).get(self._url(other, document))

        assert response.status_code == 404
