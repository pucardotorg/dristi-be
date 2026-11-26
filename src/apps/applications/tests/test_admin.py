"""Admin (spec 0033 #16.9): read-only applications, retry, *Record order on application* (#1.2)."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.applications.models import Application, OfficeMembership
from apps.applications.tasks import run_type_workflow

from .factories import pass_order, submitted

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(world):
    user = get_user_model().objects.create_superuser(
        mobile_number="+919999900001", password="x", name="Admin"
    )
    client = Client()
    client.force_login(user)
    return client


def test_changelists_render(admin_client, world):
    submitted(world)
    OfficeMembership.objects.first()
    for name in (
        "applications_application",
        "applications_applicationtype",
        "applications_applicationtransition",
        "applications_applicationcounter",
        "applications_officemembership",
    ):
        assert admin_client.get(reverse(f"admin:{name}_changelist")).status_code == 200


def test_application_change_page_has_the_record_order_link(admin_client, world):
    application = submitted(world)
    response = admin_client.get(
        reverse("admin:applications_application_change", args=[application.pk])
    )
    assert response.status_code == 200
    assert b"Record order on application" in response.content


def test_record_order_onboards(admin_client, world):
    application = submitted(world)
    url = reverse("admin:applications_application_record_order", args=[application.pk])
    assert admin_client.get(url).status_code == 200
    response = admin_client.post(
        url,
        {
            "order_number": "ORD/1/2026",
            "order_date": "2026-11-12",
            "onboard": "on",
            "bring_back_on": "2026-11-20",
        },
    )
    assert response.status_code == 302
    application.refresh_from_db()
    assert application.status == "PENDING_DECISION"
    # The same order recorded twice acts once (deterministic order id).
    admin_client.post(
        url,
        {
            "order_number": "ORD/1/2026",
            "order_date": "2026-11-12",
            "onboard": "on",
            "bring_back_on": "2026-11-20",
        },
    )
    assert application.transitions.filter(action="ONBOARD").count() == 1


def test_record_order_refused_on_a_closed_application(admin_client, world):
    application = submitted(world)
    pass_order(application, onboard=False, decides=True, outcome="DISMISSED")
    url = reverse("admin:applications_application_record_order", args=[application.pk])
    response = admin_client.post(
        url,
        {
            "order_number": "ORD/2",
            "order_date": "2026-11-12",
            "decides": "on",
            "outcome": "ACCEPTED",
        },
    )
    assert response.status_code == 200
    assert b"Not recorded" in response.content


def test_record_order_needs_permission(world):
    staff = get_user_model().objects.create_user(
        mobile_number="+919999900002", password="x", name="Staff", is_staff=True
    )
    from django.contrib.auth.models import Permission

    staff.user_permissions.add(Permission.objects.get(codename="view_application"))
    client = Client()
    client.force_login(staff)
    application = submitted(world)
    url = reverse("admin:applications_application_record_order", args=[application.pk])
    assert client.get(url).status_code == 302
    assert Application.objects.get(pk=application.pk).status == "PENDING_REVIEW"


def test_retry_type_workflow_action(admin_client, world):
    application = submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
    pass_order(application, onboard=True, decides=True, outcome="ACCEPTED")
    with mock.patch.object(run_type_workflow, "send") as send:
        response = admin_client.post(
            reverse("admin:applications_application_changelist"),
            {"action": "retry_type_workflow", "_selected_action": [str(application.pk)]},
        )
    assert response.status_code == 302
    send.assert_called_once_with(str(application.pk))


def test_type_code_is_read_only_once_created(admin_client):
    from apps.applications.models import ApplicationType

    row = ApplicationType.objects.get(code="BAIL")
    response = admin_client.get(reverse("admin:applications_applicationtype_change", args=[row.pk]))
    assert response.status_code == 200
    assert b'name="code"' not in response.content
