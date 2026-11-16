"""Human-readable request numbers, ``KL-REQ-00001`` (spec 0010 section 1.1)."""

import json

import pytest
from django.urls import reverse

from apps.api.errors import BusinessError
from apps.core.models import Configuration
from apps.dristi_requests import errors, services
from apps.dristi_requests.exceptions import ApprovalRoutingError
from apps.dristi_requests.models import Request, RequestNumberSequence
from apps.dristi_requests.numbering import format_request_number, next_request_number


def create(request_type, requester):
    """Create and submit a request of ``request_type``."""
    return services.create_request(
        request_type=request_type, requester=requester, data={"reason": "x"}
    )


@pytest.mark.django_db
class TestRequestNumber:
    """Numbers are allocated from a counter row and never change."""

    def test_numbers_are_sequential(self, simple_type, requester, approver_one):
        first = create(simple_type, requester)
        second = create(simple_type, requester)

        assert first.request_number == "KL-REQ-00001"
        assert second.request_number == "KL-REQ-00002"
        assert str(first) == "KL-REQ-00001"

    def test_format_pads_to_five_digits_without_truncating(self):
        assert format_request_number("KL-REQ", 1) == "KL-REQ-00001"
        assert format_request_number("KL-REQ", 99999) == "KL-REQ-99999"
        assert format_request_number("KL-REQ", 100000) == "KL-REQ-100000"
        assert format_request_number("KL-REQ", 1234567) == "KL-REQ-1234567"

    def test_sequence_continues_past_99999(self, simple_type, requester, approver_one):
        RequestNumberSequence.objects.create(prefix="KL-REQ", value=99998)

        last_five_digit = create(simple_type, requester)
        first_six_digit = create(simple_type, requester)
        next_one = create(simple_type, requester)

        assert last_five_digit.request_number == "KL-REQ-99999"
        assert first_six_digit.request_number == "KL-REQ-100000"
        assert next_one.request_number == "KL-REQ-100001"
        first_six_digit.refresh_from_db()
        assert first_six_digit.request_number == "KL-REQ-100000"
        assert RequestNumberSequence.objects.get(prefix="KL-REQ").value == 100001

    def test_draft_gets_a_number(self, simple_type, requester):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}, submit=False
        )

        assert request.request_number == "KL-REQ-00001"

    def test_resubmit_keeps_the_number(self, simple_type, requester, approver_one):
        request = create(simple_type, requester)
        services.decide(request.current_approval, "rejected", actor=approver_one, comments="no")
        request.refresh_from_db()

        services.resubmit(request, actor=requester)
        request.refresh_from_db()

        assert request.version == 2
        assert request.request_number == "KL-REQ-00001"

    def test_failed_creation_does_not_leave_a_gap(self, simple_type, requester, make_user):
        with pytest.raises(ApprovalRoutingError):
            create(simple_type, requester)
        assert Request.objects.count() == 0
        make_user("late-approver@example.com", groups=["LEVEL_ONE"])

        assert create(simple_type, requester).request_number == "KL-REQ-00001"

    def test_state_code_is_normalised(self, state_code):
        state_code.config_value = " kl "
        state_code.save()

        assert next_request_number() == "KL-REQ-00001"

    def test_changing_the_state_code_starts_a_new_series(self, state_code):
        assert next_request_number() == "KL-REQ-00001"
        state_code.config_value = "TN"
        state_code.save()

        assert next_request_number() == "TN-REQ-00001"
        assert set(RequestNumberSequence.objects.values_list("prefix", "value")) == {
            ("KL-REQ", 1),
            ("TN-REQ", 1),
        }


@pytest.mark.django_db
class TestStateCodeNotConfigured:
    """Without a valid ``tenant.state_code`` no request is created."""

    @pytest.mark.parametrize("value", ["", "K", "KERALA", "K1", "K-L"])
    def test_malformed_state_code(self, state_code, value):
        state_code.config_value = value
        state_code.save()

        with pytest.raises(BusinessError) as excinfo:
            next_request_number()

        assert excinfo.value.error == errors.REQUEST_NUMBERING_NOT_CONFIGURED

    def test_inactive_state_code(self, state_code):
        state_code.is_active = False
        state_code.save()

        with pytest.raises(BusinessError) as excinfo:
            next_request_number()

        assert excinfo.value.error == errors.REQUEST_NUMBERING_NOT_CONFIGURED

    def test_missing_state_code_fails_the_create(
        self, state_code, auth_client, simple_type, requester, approver_one
    ):
        state_code.delete()

        response = auth_client(requester).post(
            reverse("request-list"),
            {"request_type": "SIMPLE", "attributes": json.dumps({"reason": "x"})},
            format="multipart",
        )

        assert response.status_code == 503
        assert response.json()["errors"][0]["code"] == "E02008"
        assert Request.objects.count() == 0
        assert not Configuration.objects.filter(config_set="tenant").exists()


@pytest.mark.django_db
class TestRequestNumberAPI:
    """The number is returned read-only and can be filtered on."""

    def test_returned_on_create_and_read(self, auth_client, simple_type, requester, approver_one):
        client = auth_client(requester)

        created = client.post(
            reverse("request-list"),
            {
                "request_type": "SIMPLE",
                "attributes": json.dumps({"reason": "x"}),
                "request_number": "KL-REQ-12345",
            },
            format="multipart",
        ).json()
        listed = client.get(reverse("request-list")).json()["results"]

        assert created["request_number"] == "KL-REQ-00001"
        assert listed[0]["request_number"] == "KL-REQ-00001"

    def test_list_filters_by_request_number(
        self, auth_client, simple_type, requester, approver_one
    ):
        create(simple_type, requester)
        second = create(simple_type, requester)
        client = auth_client(requester)

        found = client.get(reverse("request-list"), {"request_number": "kl-req-00002"})
        missing = client.get(reverse("request-list"), {"request_number": "KL-REQ-00009"})

        assert [row["id"] for row in found.json()["results"]] == [str(second.pk)]
        assert missing.json()["results"] == []

    def test_filter_is_scoped_to_own_requests(
        self, auth_client, simple_type, requester, outsider, approver_one
    ):
        create(simple_type, requester)

        response = auth_client(outsider).get(
            reverse("request-list"), {"request_number": "KL-REQ-00001"}
        )

        assert response.json()["results"] == []

    def test_approvals_filter_by_request_number(
        self, auth_client, simple_type, requester, approver_one
    ):
        create(simple_type, requester)
        second = create(simple_type, requester)

        response = auth_client(approver_one).get(
            reverse("request-approval-list"), {"request_number": "KL-REQ-00002"}
        )

        assert [row["request"] for row in response.json()["results"]] == [str(second.pk)]
