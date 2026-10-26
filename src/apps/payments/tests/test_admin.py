"""Operator actions in the admin (spec 0017 #9.3, #9.5, #10)."""

import pytest
from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.payments.enums import PaymentStatus
from apps.payments.models import Demand, Payment
from apps.payments.services import PaymentService

from .fakes import FakeProvider, status
from .helpers import item_ids

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_request(make_user):
    staff = make_user("Operator", is_staff=True, is_superuser=True)
    request = RequestFactory().post("/admin/payments/payment/")
    request.user = staff
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def payment_admin():
    return site._registry[Payment]


def test_everything_is_read_only(admin_request):
    for model in (Demand, Payment):
        model_admin = site._registry[model]
        assert not model_admin.has_add_permission(admin_request)
        assert not model_admin.has_change_permission(admin_request)
        assert not model_admin.has_delete_permission(admin_request)
        assert "id" in model_admin.get_readonly_fields(admin_request)


def test_confirm_without_provider(admin_request, raise_demand, user, no_provider):
    demand = raise_demand()
    payment = PaymentService.create_payment(
        demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
    ).payment
    payment_admin().confirm_without_provider(admin_request, Payment.objects.all())
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.updated_by == admin_request.user
    # Confirming again reports nothing new and credits nothing twice.
    payment_admin().confirm_without_provider(admin_request, Payment.objects.all())
    demand.refresh_from_db()
    assert demand.paid_amount == demand.total_amount


def test_recheck_and_clear_reconciliation(admin_request, raise_demand, user, fake_provider):
    demand = raise_demand()
    payment = PaymentService.create_payment(
        demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
    ).payment
    FakeProvider.statuses = {
        payment.provider_payment_id: status(payment.provider_payment_id, "SUCCESS", "1.00")
    }
    payment_admin().recheck_with_provider(admin_request, Payment.objects.all())
    payment.refresh_from_db()
    assert payment.needs_reconciliation

    payment_admin().clear_reconciliation(admin_request, Payment.objects.all())
    payment.refresh_from_db()
    assert not payment.needs_reconciliation
    assert payment.status == PaymentStatus.PENDING


def test_recheck_reports_an_unreachable_provider(admin_request, raise_demand, user, fake_provider):
    from apps.payments.providers.base import ProviderTransientError

    demand = raise_demand()
    PaymentService.create_payment(
        demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
    )
    FakeProvider.fetch_error = ProviderTransientError("DOWN")
    payment_admin().recheck_with_provider(admin_request, Payment.objects.all())
    messages = [str(m) for m in admin_request._messages]
    assert any("DOWN" in m for m in messages)


def staff_with(make_user, *codenames):
    """A staff user holding only the given payments permissions."""
    from django.contrib.auth.models import Permission

    staff = make_user("Clerk", is_staff=True)
    staff.user_permissions.set(
        Permission.objects.filter(content_type__app_label="payments", codename__in=codenames)
    )
    return type(staff).objects.get(pk=staff.pk)  # drop the cached permissions


def actions_for(user):
    request = RequestFactory().get("/admin/payments/payment/")
    request.user = user
    return set(payment_admin().get_actions(request))


def test_view_only_staff_cannot_move_money(make_user):
    """Actions without permissions= are offered to anyone who can view the list."""
    viewer = staff_with(make_user, "view_payment")
    assert actions_for(viewer).isdisjoint(
        {"confirm_without_provider", "clear_reconciliation", "recheck_with_provider"}
    )


def test_each_action_needs_its_own_permission(make_user):
    operator = staff_with(make_user, "view_payment", "confirm_payment_manually")
    assert "confirm_without_provider" in actions_for(operator)
    assert "clear_reconciliation" not in actions_for(operator)

    reconciler = staff_with(
        make_user, "view_payment", "resolve_payment_reconciliation", "recheck_payment_status"
    )
    assert {"clear_reconciliation", "recheck_with_provider"} <= actions_for(reconciler)
    assert "confirm_without_provider" not in actions_for(reconciler)
