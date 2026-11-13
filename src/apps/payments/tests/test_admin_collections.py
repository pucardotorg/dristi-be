"""The collection desk in the Django admin (spec 0032 #10, #17.4)."""

import pytest
from django.contrib.admin.sites import site
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.payments.enums import AttestationOutcome, PaymentStatus
from apps.payments.models import Payment, PaymentAttestation
from apps.payments.selectors import IST
from apps.payments.services import PaymentService

from .helpers import item_ids

pytestmark = pytest.mark.django_db

CHANGELIST = reverse("admin:payments_payment_changelist")


def change_url(payment):
    return reverse("admin:payments_payment_change", args=[payment.pk])


def record_url(payment, late=False):
    name = "record_late_collection" if late else "record_collection"
    return reverse(f"admin:payments_payment_{name}", args=[payment.pk])


@pytest.fixture
def staff(make_user, grant):
    """Staff who may view payments and record (late) collections and cancel them."""

    def factory(*codenames, name="Clerk"):
        user = make_user(name, is_staff=True)
        return grant(user, "view_payment", *codenames)

    return factory


def browser(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def pending(raise_demand, user, attested_provider):
    demand = raise_demand()
    return PaymentService.create_payment(
        demand=demand,
        demand_item_ids=item_ids(demand),
        client_request_id="k",
        provider="counter",
        actor=user,
    ).payment


@pytest.fixture
def gateway_payment(raise_demand, user, attested_provider):
    demand = raise_demand(reference_id="gw")
    return PaymentService.create_payment(
        demand=demand, demand_item_ids=item_ids(demand), client_request_id="g", actor=user
    ).payment


def form_body(**overrides):
    body = {
        "amount": "37.50",
        "method": "CASH",
        "receipt_number": "CJM/1",
        "collected_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
        "remarks": "",
    }
    body.update(overrides)
    return body


def test_awaiting_collection_filter(pending, gateway_payment, staff):
    response = browser(staff()).get(CHANGELIST, {"awaiting_collection": "yes"})
    assert response.status_code == 200
    shown = list(response.context["cl"].result_list)
    assert shown == [pending]


def test_record_button_needs_the_permission_and_an_open_request(pending, staff):
    without = browser(staff()).get(change_url(pending))
    assert "Record collection" not in without.content.decode()

    clerk = staff("record_payment_collection")
    page = browser(clerk).get(change_url(pending)).content.decode()
    assert "Record collection" in page and record_url(pending) in page


def test_no_button_for_gateway_payments(gateway_payment, staff):
    clerk = staff("record_payment_collection", "record_late_payment_collection")
    page = browser(clerk).get(change_url(gateway_payment)).content.decode()
    assert "Record collection" not in page and "Record late collection" not in page
    assert browser(clerk).get(record_url(gateway_payment)).status_code == 404


def test_late_button_only_for_closed_requests(pending, staff):
    late_clerk = staff("record_payment_collection", "record_late_payment_collection")
    assert (
        "Record late collection"
        not in browser(late_clerk).get(change_url(pending)).content.decode()
    )
    PaymentService.fail_payment(pending, failure_code="EXPIRED")
    page = browser(late_clerk).get(change_url(pending)).content.decode()
    assert "Record late collection" in page
    plain = staff("record_payment_collection", name="Plain")
    assert "Record late collection" not in browser(plain).get(change_url(pending)).content.decode()


def test_form_shows_the_request_and_method_fields(pending, staff):
    response = browser(staff("record_payment_collection")).get(record_url(pending))
    assert response.status_code == 200
    page = response.content.decode()
    assert pending.provider_payment_id in page
    assert pending.payment_number in page
    assert "******" in page  # masked phone
    assert "Demand draft: DD number" in page


def test_valid_form_credits(pending, staff):
    clerk = staff("record_payment_collection")
    response = browser(clerk).post(record_url(pending), form_body())
    assert response.status_code == 302
    pending.refresh_from_db()
    assert pending.status == PaymentStatus.SUCCESS
    attestation = PaymentAttestation.objects.get()
    assert attestation.created_by == clerk
    assert attestation.outcome == AttestationOutcome.CREDITED


def test_collected_at_is_entered_in_ist(pending, staff):
    """The form reads 11:42 as 11:42 IST (06:12 UTC), whatever TIME_ZONE is."""

    clerk = staff("record_payment_collection")
    now_ist = timezone.localtime(timezone.now(), timezone=IST).replace(second=0, microsecond=0)
    browser(clerk).post(
        record_url(pending), form_body(collected_at=now_ist.strftime("%Y-%m-%d %H:%M:%S"))
    )
    assert PaymentAttestation.objects.get().collected_at == now_ist


def test_detail_fields_of_the_chosen_method_are_sent(pending, staff, attested_provider):
    clerk = staff("record_payment_collection")
    browser(clerk).post(
        record_url(pending), form_body(method="DD", **{"detail__DD__number": "123456"})
    )
    assert attested_provider.attest_calls[0].details == {"number": "123456"}


def test_business_error_is_shown_on_the_field(pending, staff):
    clerk = staff("record_payment_collection")
    response = browser(clerk).post(record_url(pending), form_body(amount="1.00"))
    assert response.status_code == 200
    assert response.context["form"].errors["amount"]
    assert not PaymentAttestation.objects.exists()
    pending.refresh_from_db()
    assert pending.status == PaymentStatus.PENDING


def test_non_field_error_is_shown_on_the_form(pending, staff, user, grant):
    payer = grant(user, "view_payment", "record_payment_collection")
    payer.is_staff = True
    payer.save()
    response = browser(payer).post(record_url(pending), form_body())
    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    assert not PaymentAttestation.objects.exists()


def test_form_needs_the_permission(pending, staff):
    assert browser(staff()).get(record_url(pending)).status_code == 403
    clerk = staff("record_payment_collection")
    assert browser(clerk).get(record_url(pending, late=True)).status_code == 403


def test_closed_request_redirects_from_the_normal_form(pending, staff):
    PaymentService.cancel_payment(pending)
    response = browser(staff("record_payment_collection")).get(record_url(pending))
    assert response.status_code == 302


def test_late_form_flags(pending, staff):
    PaymentService.fail_payment(pending, failure_code="EXPIRED")
    clerk = staff("record_late_payment_collection")
    response = browser(clerk).post(record_url(pending, late=True), form_body())
    assert response.status_code == 302
    assert PaymentAttestation.objects.get().outcome == AttestationOutcome.FLAGGED
    pending.refresh_from_db()
    assert pending.status == PaymentStatus.FAILED and pending.needs_reconciliation


def test_cancel_action_requires_permission_and_reason(pending, gateway_payment, staff):
    def actions(user):
        from django.test import RequestFactory

        request = RequestFactory().get(CHANGELIST)
        request.user = user
        return set(site._registry[Payment].get_actions(request))

    assert "cancel_collection_request" not in actions(staff())
    canceller = staff("cancel_payment_collection")
    assert "cancel_collection_request" in actions(canceller)

    client = browser(canceller)
    selected = [str(pending.pk), str(gateway_payment.pk)]
    intermediate = client.post(
        CHANGELIST, {"action": "cancel_collection_request", "_selected_action": selected}
    )
    assert intermediate.status_code == 200
    assert pending.provider_payment_id in intermediate.content.decode()

    no_reason = client.post(
        CHANGELIST,
        {"action": "cancel_collection_request", "_selected_action": selected, "apply": "1"},
    )
    assert no_reason.status_code == 200
    pending.refresh_from_db()
    assert pending.status == PaymentStatus.PENDING

    done = client.post(
        CHANGELIST,
        {
            "action": "cancel_collection_request",
            "_selected_action": selected,
            "apply": "1",
            "reason": "Payer asked",
        },
    )
    assert done.status_code == 302
    pending.refresh_from_db()
    gateway_payment.refresh_from_db()
    assert pending.status == PaymentStatus.CANCELLED
    assert pending.failure_message == "Payer asked"
    assert gateway_payment.status == PaymentStatus.PENDING  # not attested: untouched


def test_admin_search_normalises_a_reference(pending, staff):
    response = browser(staff()).get(CHANGELIST, {"q": pending.provider_payment_id.lower()})
    assert list(response.context["cl"].result_list) == [pending]


def test_attestation_admin_is_read_only(pending, staff, make_user, grant):
    PaymentService.record_collection(
        provider="counter",
        provider_payment_id=pending.provider_payment_id,
        amount=pending.amount,
        method="CASH",
        receipt_number="R-1",
        collected_at=timezone.now(),
        actor=grant(make_user("Recorder"), "record_payment_collection"),
    )
    model_admin = site._registry[PaymentAttestation]
    superuser = make_user("Root", is_staff=True, is_superuser=True)
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = superuser
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)
    response = browser(superuser).get(reverse("admin:payments_paymentattestation_changelist"))
    assert response.status_code == 200
    assert "R-1" in response.content.decode()
