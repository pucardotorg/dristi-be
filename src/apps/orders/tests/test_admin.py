"""Admin (spec 0039 #12.8): the catalogue is editable, orders are read only."""

from unittest import mock

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory

from apps.orders import handlers
from apps.orders.admin import OrderAdmin, OrderItemTypeAdmin, OrderItemTypeForm
from apps.orders.models import Order, OrderItemType, OrderRoznama, OrderType, OrderWorkflowRun

from .factories import make_user

pytestmark = pytest.mark.django_db


def request_for(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.fixture
def admin_user_():
    return get_user_model().objects.create_superuser(
        mobile_number="+919999900001", password="x", name="Admin"
    )


def test_orders_runs_and_roznamas_are_read_only(admin_user_, case):
    request = request_for(admin_user_)
    for model in (Order, OrderWorkflowRun, OrderRoznama):
        model_admin = site._registry[model]
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)


def test_the_catalogue_and_types_are_editable_but_never_deleted(admin_user_):
    request = request_for(admin_user_)
    for model in (OrderItemType, OrderType):
        model_admin = site._registry[model]
        assert model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)


def _form(item, **changes):
    data = {
        "code": item.code,
        "label": item.label,
        "availability": item.availability,
        "category": item.category,
        "target_type": item.target_type,
        "trigger_phase": item.trigger_phase,
        "sequence": item.sequence,
        "field_schema": '{"fields": []}',
        "has_workflow": "on" if item.has_workflow else "",
        "is_active": "on",
    }
    data.update(changes)
    return OrderItemTypeForm(data=data, instance=item)


def test_saving_a_workflow_item_without_a_handler_is_refused():
    item = OrderItemType.objects.get(code="JUDGEMENT")
    assert _form(item).is_valid()
    refused = _form(item, has_workflow="on")
    assert not refused.is_valid()
    assert "handler" in str(refused.errors)


def test_saving_an_invalid_field_schema_is_refused():
    item = OrderItemType.objects.get(code="COST")
    form = _form(
        item,
        field_schema='{"fields": [{"key": "A", "label": "x", "input": "TEXT"}]}',
        has_workflow="on",
    )
    assert not form.is_valid()
    assert "field_schema" in form.errors or "field_schema" in str(form.errors)


def test_retry_failed_steps_calls_the_service(admin_user_, ready):
    model_admin = OrderAdmin(Order, site)
    request = request_for(admin_user_)
    with mock.patch("apps.orders.admin.triggering.retry_failed", return_value=2) as retry:
        with mock.patch.object(model_admin, "message_user") as message:
            model_admin.retry_failed_steps(request, Order.objects.filter(pk=ready.pk))
    retry.assert_called_once_with(ready.pk)
    assert "2 step" in message.call_args.args[1]
    assert handlers and OrderItemTypeAdmin


def test_the_order_pages_items_and_runs_cannot_be_added_to(admin_user_, ready):
    request = request_for(admin_user_)
    for inline_class in OrderAdmin.inlines:
        inline = inline_class(Order, site)
        assert not inline.has_add_permission(request, obj=ready)
        assert not inline.can_delete


def test_retrying_runs_retries_each_of_their_orders_once(admin_user_, ready, staff, signer):
    from apps.orders.admin import OrderWorkflowRunAdmin
    from apps.orders.enums import RunStatus
    from apps.orders.services import triggering

    from .test_triggering import COST, trigger

    order = trigger(ready, staff, signer, ("COST", COST), "COGNIZANCE")
    order.runs.update(status=RunStatus.FAILED, attempts=3)
    model_admin = OrderWorkflowRunAdmin(OrderWorkflowRun, site)
    with mock.patch.object(triggering, "enqueue_on_commit") as enqueue:
        with mock.patch.object(model_admin, "message_user") as message:
            model_admin.retry(request_for(admin_user_), order.runs.all())
    count = order.runs.count()
    assert count > 1
    enqueue.assert_called_once_with(order.pk)  # several runs of one order: one retry
    assert f"{count} step" in message.call_args.args[1]
    assert set(order.runs.values_list("status", "attempts")) == {(RunStatus.PENDING, 0)}


def _staff_with(*codenames):
    user = make_user(name="Operator")
    user.is_staff = True
    user.save()
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="orders", codename=codename)
        )
    return type(user).objects.get(pk=user.pk)


@pytest.mark.parametrize(
    ("model", "model_name"), [(Order, "order"), (OrderWorkflowRun, "orderworkflowrun")]
)
def test_retry_needs_the_change_permission_not_view(model, model_name):
    model_admin = site._registry[model]
    request = RequestFactory().get("/")

    request.user = _staff_with(f"view_{model_name}")
    assert not any(name.startswith("retry") for name in model_admin.get_actions(request))

    request.user = _staff_with(f"view_{model_name}", f"change_{model_name}")
    assert any(name.startswith("retry") for name in model_admin.get_actions(request))


def test_a_view_only_user_cannot_run_the_retry_action(client, case, order):
    viewer = _staff_with("view_order")
    viewer.set_password("x")
    viewer.save()
    client.force_login(viewer)
    response = client.post(
        "/admin/orders/order/",
        {"action": "retry_failed_steps", "_selected_action": [str(order.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    assert not OrderWorkflowRun.objects.exists()
    assert b"step(s) queued" not in response.content
