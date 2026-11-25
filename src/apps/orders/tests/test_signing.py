"""Signing (spec 0039 #8): e-sign start and confirm, numbers, dates, the Roznama."""

import datetime
import uuid

import pytest
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.core.models import Configuration
from apps.esign.models import ESignTransaction
from apps.hearings.services import courtroom as hearing_courtroom
from apps.orders import ports, rendering
from apps.orders.enums import NumberSeries, OrderStatus, RoznamaStatus
from apps.orders.models import Order, OrderNumberCounter, OrderRoznama, OrderType
from apps.orders.permissions import can_sign_via_esign
from apps.orders.services import diary, drafting, lifecycle, signing

from .factories import TODAY, code

pytestmark = pytest.mark.django_db


@pytest.fixture
def started(monkeypatch):
    """Stub the file store and the e-sign start; record what they were given."""
    calls = {"stored": [], "initiated": []}

    def store(order, content, name, actor):
        assert content.startswith(b"%PDF")
        calls["stored"].append(name)
        return f"file-{len(calls['stored'])}"

    def initiate(order, actor, file_id):
        calls["initiated"].append(file_id)
        return "initiation"

    monkeypatch.setattr(signing, "_store", store)
    monkeypatch.setattr(signing, "_initiate", initiate)
    return calls


@pytest.fixture
def sent(ready, staff):
    return lifecycle.send_for_signing(ready.pk, actor=staff)


def success(order, signer, *, source="file-1", signed="signed-1", **overrides):
    values = {
        "module": "orders",
        "entity_type": "ORDER",
        "entity_id": str(order.pk),
        "signer": signer,
        "provider": "mock",
        "provider_transaction_id": f"p-{uuid.uuid4()}",
        "source_file_id": source,
        "signed_file_id": signed,
        "status": "SUCCESS",
        "expires_at": timezone.now() + datetime.timedelta(hours=1),
    }
    values.update(overrides)
    return ESignTransaction.objects.create(**values)


# -- starting ------------------------------------------------------------------------


def test_starting_allots_the_number_sets_the_date_and_stores_the_pdf(sent, signer, started):
    assert signing.start_signing(sent.pk, actor=signer) == "initiation"
    order = Order.objects.get(pk=sent.pk)
    assert order.number == f"{order.court.code}/ORD/1/2026"
    assert order.order_date == TODAY
    assert order.signing_file_id == "file-1"
    assert started["initiated"] == ["file-1"]


def test_the_number_is_allotted_once_and_kept_across_retries(sent, signer, started):
    signing.start_signing(sent.pk, actor=signer)
    first = Order.objects.get(pk=sent.pk).number
    signing.start_signing(sent.pk, actor=signer)
    assert Order.objects.get(pk=sent.pk).number == first
    assert OrderNumberCounter.objects.get(court=sent.court, series="ORDER").last_value == 1


def test_numbers_run_on_within_a_courtroom_and_year(ready, staff, signer, started, case, courtroom):
    from apps.hearings.tests.factories import make_case

    other = drafting.create_outside_hearing(case_id=make_case(courtroom).pk, actor=staff)
    drafting.edit_text(other.pk, "<p>x</p>", actor=staff)
    from apps.orders.services import next_hearing

    next_hearing.set_next_hearing(other.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.send_for_signing(other.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.start_signing(other.pk, actor=signer)
    signing.start_signing(ready.pk, actor=signer)
    assert Order.objects.get(pk=other.pk).number.endswith("/ORD/1/2026")
    assert Order.objects.get(pk=ready.pk).number.endswith("/ORD/2/2026")


def test_a_method_not_enabled_is_refused_and_dsc_is_not_started_here(sent, signer, started):
    with pytest.raises(BusinessError) as excinfo:
        signing.start_signing(sent.pk, actor=signer, method="DSC")
    assert code(excinfo) == "E14017"
    # Enabling DSC in configuration does not make this endpoint start an e-sign for it.
    Configuration.objects.update_or_create(
        config_set="signing", config_key="methods", defaults={"config_value": "AADHAAR_ESIGN,DSC"}
    )
    with pytest.raises(BusinessError) as excinfo:
        signing.start_signing(sent.pk, actor=signer, method="DSC")
    assert code(excinfo) == "E14017"
    Configuration.objects.filter(config_set="signing").update(config_value="DSC")
    with pytest.raises(BusinessError) as excinfo:
        signing.start_signing(sent.pk, actor=signer, method="AADHAAR_ESIGN")
    assert code(excinfo) == "E14017"
    assert started["initiated"] == []


def test_only_an_order_sent_for_signing_can_be_started(ready, signer, started):
    with pytest.raises(BusinessError) as excinfo:
        signing.start_signing(ready.pk, actor=signer)
    assert code(excinfo) == "E14001"


# -- confirming ------------------------------------------------------------------------


def test_confirming_a_successful_transaction_signs_the_order(sent, signer, started):
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    order = signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert order.status == OrderStatus.SIGNED
    assert order.signed_file_id == "signed-1"
    assert order.signed_by == signer
    assert order.signing_method == "AADHAAR_ESIGN"


def test_confirm_is_idempotent(sent, signer, started):
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    first = signing.record_signature(sent.pk, txn.pk, actor=signer)
    again = signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert again.signed_at == first.signed_at


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "PENDING", "signed_file_id": ""},
        {"entity_id": str(uuid.uuid4())},
        {"source_file_id": "from-before-a-move-back"},
    ],
)
def test_confirm_refuses_a_transaction_that_is_not_this_orders_current_signing(
    sent, signer, started, bad
):
    signing.start_signing(sent.pk, actor=signer)
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(sent.pk, success(sent, signer, **bad).pk, actor=signer)
    assert code(excinfo) == "E14015"
    assert Order.objects.get(pk=sent.pk).status == OrderStatus.SENT_FOR_SIGNING


def test_confirm_refuses_another_users_transaction(sent, signer, started, staff):
    signing.start_signing(sent.pk, actor=signer)
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(sent.pk, success(sent, staff).pk, actor=signer)
    assert code(excinfo) == "E14015"


def test_a_signature_begun_before_a_move_back_cannot_be_recorded(sent, signer, started, staff):
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    lifecycle.move_to_draft(sent.pk, actor=staff)
    lifecycle.send_for_signing(sent.pk, actor=staff)
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert code(excinfo) == "E14015"


def test_a_transaction_confirmed_while_the_order_is_back_in_draft_is_e14015(
    sent, signer, started, staff
):
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    lifecycle.move_to_draft(sent.pk, actor=staff)
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert code(excinfo) == "E14015"


def test_confirming_the_next_day_is_refused_and_the_order_is_signed_again(
    sent, signer, started, settings
):
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    Configuration.objects.update_or_create(
        config_set="hearings",
        config_key="business_date_override",
        defaults={"config_value": (TODAY + datetime.timedelta(days=1)).isoformat()},
    )
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert code(excinfo) == "E14015"
    order = Order.objects.get(pk=sent.pk)
    assert order.signing_file_id == "" and order.status == OrderStatus.SENT_FOR_SIGNING
    signing.start_signing(sent.pk, actor=signer)
    assert Order.objects.get(pk=sent.pk).order_date == TODAY + datetime.timedelta(days=1)
    assert Order.objects.get(pk=sent.pk).number == order.number


def test_signing_with_complete_data_triggers(ready, staff, signer, started):
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.start_signing(ready.pk, actor=signer)
    order = signing.record_signature(ready.pk, success(ready, signer).pk, actor=signer)
    assert order.status == OrderStatus.TRIGGERED


# -- the e-sign authorizer ---------------------------------------------------------------------


def test_a_direct_esign_for_an_order_needs_the_signer_role_and_an_order_sent_for_signing(
    sent, ready, signer, staff, drafter
):
    Order.objects.filter(pk=sent.pk).update(signing_file_id="file-1")
    kwargs = {"entity_type": "ORDER", "entity_id": str(sent.pk), "file_id": "file-1"}
    assert can_sign_via_esign(user=signer, **kwargs) is True
    assert can_sign_via_esign(user=drafter, **kwargs) is False
    assert (
        can_sign_via_esign(user=signer, entity_type="ORDER", entity_id="nope", file_id="file-1")
        is False
    )
    Order.objects.filter(pk=sent.pk).update(status=OrderStatus.DRAFT)
    assert can_sign_via_esign(user=signer, **kwargs) is False


def test_a_direct_esign_must_name_the_file_the_order_is_about_to_sign(sent, signer):
    Order.objects.filter(pk=sent.pk).update(signing_file_id="file-1")
    kwargs = {"user": signer, "entity_type": "ORDER", "entity_id": str(sent.pk)}
    assert can_sign_via_esign(**kwargs, file_id="someone-elses.pdf") is False
    assert can_sign_via_esign(**kwargs) is False


def test_a_retry_passes_only_while_its_file_is_still_the_current_one(sent, signer, staff):
    Order.objects.filter(pk=sent.pk).update(signing_file_id="file-1")
    kwargs = {"user": signer, "entity_type": "ORDER", "entity_id": str(sent.pk)}
    success(sent, signer, source="file-1", status="FAILURE")
    assert can_sign_via_esign(**kwargs, file_id="file-1") is True
    # Cleared (a new business date, a title or type change): the old file can never be recorded.
    Order.objects.filter(pk=sent.pk).update(signing_file_id="")
    assert can_sign_via_esign(**kwargs, file_id="file-1") is False
    Order.objects.filter(pk=sent.pk).update(signing_file_id="file-2")
    assert can_sign_via_esign(**kwargs, file_id="file-1") is False


def test_the_roznama_path_is_bound_to_the_roznama_file(normal_triggered, signer):
    roznama = OrderRoznama.objects.get(order=normal_triggered)
    OrderRoznama.objects.filter(pk=roznama.pk).update(signing_file_id="roz-1")
    kwargs = {"user": signer, "entity_type": "ORDER", "entity_id": str(normal_triggered.pk)}
    assert can_sign_via_esign(**kwargs, file_id="roz-1") is True
    assert can_sign_via_esign(**kwargs, file_id="other") is False


def test_the_authorizer_is_registered_with_esign():
    from apps.esign import permissions

    assert permissions.resolve_authorizer("ORDER") is can_sign_via_esign


# -- Gujarat -------------------------------------------------------------------------------------


@pytest.fixture
def gujarat():
    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "GJ"}
    )


@pytest.fixture
def normal_triggered(gujarat, case, staff, signer, started):
    """A triggered normal order outside a hearing, in Gujarat."""
    from apps.orders.services import next_hearing

    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code="NORMAL")
    drafting.edit_text(order.pk, "<p>Heard.</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.mark_complete(order.pk, actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    signing.start_signing(order.pk, actor=signer)
    return signing.record_signature(order.pk, success(order, signer).pk, actor=signer)


def test_a_roznama_is_created_only_when_a_normal_order_is_triggered(normal_triggered, record_ports):
    roznama = OrderRoznama.objects.get(order=normal_triggered)
    assert roznama.status == RoznamaStatus.AWAITING_SIGNATURE
    assert roznama.number == ""
    assert "sign_roznama" in [args[1] for n, args, _ in record_ports if n == "open_task"]


def test_a_roznama_type_order_has_no_roznama_and_is_numbered_from_the_roznama_series(
    gujarat, case, staff, signer, started
):
    from apps.orders.services import next_hearing

    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code="ROZNAMA")
    drafting.edit_text(order.pk, "<p>x</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.mark_complete(order.pk, actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    signing.start_signing(order.pk, actor=signer)
    signed = signing.record_signature(order.pk, success(order, signer).pk, actor=signer)
    assert "/RZN/" in signed.number
    assert not OrderRoznama.objects.filter(order=order).exists()
    assert OrderNumberCounter.objects.filter(series=NumberSeries.ROZNAMA).exists()


def test_signing_a_roznama_triggers_nothing_and_changes_nothing_on_the_order(
    normal_triggered, signer, started, record_ports
):
    before = Order.objects.get(pk=normal_triggered.pk)
    signing.start_roznama_signing(normal_triggered.pk, actor=signer)
    roznama = OrderRoznama.objects.get(order=normal_triggered)
    assert "/RZN/" in roznama.number
    txn = success(normal_triggered, signer, source=roznama.signing_file_id, signed="roz-signed")
    done = signing.record_roznama_signature(normal_triggered.pk, txn.pk, actor=signer)
    assert done.status == RoznamaStatus.SIGNED and done.signed_file_id == "roz-signed"
    after = Order.objects.get(pk=normal_triggered.pk)
    assert (after.status, after.signed_file_id, after.number, after.updated_at) == (
        before.status,
        before.signed_file_id,
        before.number,
        before.updated_at,
    )
    assert "sign_roznama" in [args[1] for n, args, _ in record_ports if n == "complete_task"]
    # Idempotent.
    assert signing.record_roznama_signature(normal_triggered.pk, txn.pk, actor=signer).pk == done.pk


def test_the_signer_edits_the_diary_entry_only_of_a_roznama_awaiting_signature(
    normal_triggered, signer
):
    from apps.orders import permissions

    order, _ = permissions.actionable_order(signer, normal_triggered.pk, "edit_diary_entry")
    assert order.pk == normal_triggered.pk
    roles = permissions.court_roles(signer, order.court_id)
    assert "edit_diary_entry" in permissions.allowed_for_roles(["edit_diary_entry"], roles, order)
    assert not permissions.permits(roles, "edit_diary_entry")


def test_the_roznama_text_is_editable_until_signed_and_an_edit_clears_a_signing_begun(
    normal_triggered, signer, filler, started
):
    signing.start_roznama_signing(normal_triggered.pk, actor=signer)
    roznama = OrderRoznama.objects.get(order=normal_triggered)
    txn = success(normal_triggered, signer, source=roznama.signing_file_id)
    diary.set_entry(normal_triggered.pk, same_as_text=False, text="<p>Corrected.</p>", actor=filler)
    assert OrderRoznama.objects.get(order=normal_triggered).signing_file_id == ""
    with pytest.raises(BusinessError) as excinfo:
        signing.record_roznama_signature(normal_triggered.pk, txn.pk, actor=signer)
    assert code(excinfo) == "E14015"
    signing.start_roznama_signing(normal_triggered.pk, actor=signer)
    roznama = OrderRoznama.objects.get(order=normal_triggered)
    signing.record_roznama_signature(
        normal_triggered.pk,
        success(normal_triggered, signer, source=roznama.signing_file_id).pk,
        actor=signer,
    )
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry(normal_triggered.pk, same_as_text=True, actor=filler)
    assert code(excinfo) == "E14014"
    assert ports and OrderRoznama


def test_changing_the_type_after_signing_began_voids_that_signing(case, staff, signer, started):
    from apps.core.models import Configuration
    from apps.orders.services import next_hearing

    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "GJ"}
    )
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff)
    drafting.edit_text(order.pk, "<p>x</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    signing.start_signing(order.pk, actor=signer)
    txn = success(order, signer, source="file-1")

    drafting.change_type(order.pk, "ROZNAMA", actor=staff)

    assert Order.objects.get(pk=order.pk).signing_file_id == ""
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(order.pk, txn.pk, actor=signer)
    assert excinfo.value.error.code == "E14015"
    order = Order.objects.get(pk=order.pk)
    assert order.status == OrderStatus.SENT_FOR_SIGNING and order.signed_file_id == ""

    # Signing again prepares a new PDF and allots a number in the new type's series.
    signing.start_signing(order.pk, actor=signer)
    order = Order.objects.get(pk=order.pk)
    assert order.number and order.signing_file_id == "file-2"
    signing.record_signature(
        order.pk, success(order, signer, source="file-2", signed="signed-2").pk, actor=signer
    )
    assert Order.objects.get(pk=order.pk).status == OrderStatus.SIGNED


def _flip_roll_to_absent(hearing, staff):
    from apps.cases.selectors import get_attendance_roll

    roll = get_attendance_roll(hearing.case_id)
    marks = [
        {
            "attendee_type": entry.type,
            "participant_id": entry.participant_id,
            "mark": "ABSENT",
            "appearance_mode": "",
        }
        for entry in roll
    ]
    hearing_courtroom.set_attendance(hearing_id=hearing.pk, marks=marks, actor=staff)


def test_a_signed_page_keeps_the_roll_the_file_was_signed_with(
    ready,
    hearing,
    staff,
    signer,
    started,
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.start_signing(ready.pk, actor=signer)
    order = Order.objects.get(pk=ready.pk)
    assert order.signing_attendance and all("present" in line for line in order.signing_attendance)
    signed = signing.record_signature(ready.pk, success(ready, signer).pk, actor=signer)
    assert signed.is_signed
    _flip_roll_to_absent(hearing, staff)  # the order is signed but not yet triggered
    page = rendering.render_page(Order.objects.get(pk=ready.pk))
    assert "was present" in page and "was absent" not in page


def test_a_draft_preview_reads_the_live_roll(ready, hearing, staff):
    assert "was present" in rendering.render_page(ready)
    _flip_roll_to_absent(hearing, staff)
    assert "was absent" in rendering.render_page(Order.objects.get(pk=ready.pk))


def test_an_attendance_change_after_signing_began_voids_that_signing(
    ready,
    hearing,
    staff,
    signer,
    started,
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.start_signing(ready.pk, actor=signer)
    txn = success(ready, signer)
    _flip_roll_to_absent(hearing, staff)
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(ready.pk, txn.pk, actor=signer)
    assert code(excinfo) == "E14015"
    order = Order.objects.get(pk=ready.pk)
    assert order.signing_file_id == "" and not order.is_signed
    signing.start_signing(ready.pk, actor=signer)  # signing again re-snapshots the roll
    again = Order.objects.get(pk=ready.pk)
    assert all("absent" in line for line in again.signing_attendance)
    signed = signing.record_signature(
        ready.pk, success(ready, signer, source=again.signing_file_id).pk, actor=signer
    )
    assert signed.is_signed


def test_a_signed_page_keeps_the_heading_the_file_was_signed_with(
    ready,
    staff,
    signer,
    started,
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.start_signing(ready.pk, actor=signer)
    signing.record_signature(ready.pk, success(ready, signer).pk, actor=signer)
    order = Order.objects.get(pk=ready.pk)
    heading = order.order_type.pdf_heading
    OrderType.objects.filter(pk=order.order_type_id).update(pdf_heading="Roznama")
    order = Order.objects.select_related("order_type").get(pk=ready.pk)
    assert f"<h1>{heading}</h1>" in rendering.render_page(order)


def test_a_number_that_would_not_fit_is_refused_before_it_is_saved(order, settings):
    from django.core.exceptions import ImproperlyConfigured

    from apps.orders.services import numbering

    assert Order._meta.get_field("number").max_length >= 70  # 50-char code, 10-digit sequence
    settings.ORDERS_NUMBER_FORMATTER = "apps.orders.tests.test_signing.too_long"
    with pytest.raises(ImproperlyConfigured):
        numbering.allot(order, "ORDER")


def too_long(**_):
    return "x" * 500


def test_a_signed_file_is_required_to_record_a_signature(ready, staff, signer):
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signed_file(ready.pk, "", "DSC", actor=signer)
    assert code(excinfo) == "E14015"
    ready.refresh_from_db()
    assert ready.status == "SENT_FOR_SIGNING"


# -- a title edit while sent for signing ---------------------------------------------


def test_a_signature_begun_before_a_title_edit_cannot_be_recorded(sent, signer, started, staff):
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    drafting.edit_title(sent.pk, "A new title", actor=staff)
    assert Order.objects.get(pk=sent.pk).signing_file_id == ""
    with pytest.raises(BusinessError) as excinfo:
        signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert code(excinfo) == "E14015"
    order = Order.objects.get(pk=sent.pk)
    assert order.status == OrderStatus.SENT_FOR_SIGNING
    assert order.signed_file_id == ""


def test_signing_again_after_a_title_edit_signs_the_new_pdf(sent, signer, started, staff):
    signing.start_signing(sent.pk, actor=signer)
    number = Order.objects.get(pk=sent.pk).number
    drafting.edit_title(sent.pk, "A new title", actor=staff)
    signing.start_signing(sent.pk, actor=signer)
    order = Order.objects.get(pk=sent.pk)
    assert order.signing_file_id == "file-2"
    assert order.number == number  # the title does not touch the number series
    order = signing.record_signature(
        sent.pk, success(sent, signer, source="file-2").pk, actor=signer
    )
    assert order.status == OrderStatus.SIGNED
    assert order.title == "A new title"


def test_an_unchanged_title_keeps_the_signing(sent, signer, started, staff):
    drafting.edit_title(sent.pk, "Same title", actor=staff)
    signing.start_signing(sent.pk, actor=signer)
    txn = success(sent, signer)
    drafting.edit_title(sent.pk, "  Same title ", actor=staff)
    assert Order.objects.get(pk=sent.pk).signing_file_id == "file-1"
    order = signing.record_signature(sent.pk, txn.pk, actor=signer)
    assert order.status == OrderStatus.SIGNED


def test_the_signed_pdf_prints_the_saved_roll_even_if_an_edit_is_reverted(
    ready, hearing, staff, signer, started, monkeypatch
):
    """A roll edit committed between the snapshot and the render, then reverted, changes
    neither the PDF nor the check at confirmation: both use the one snapshot."""
    from .factories import mark_roll

    printed = []
    real_render, real_facts = rendering.render_pdf, rendering.page_facts

    def facts(order, **kwargs):
        result = real_facts(order, **kwargs)
        printed.append(result["attendance"])
        return result

    def render_after_an_edit(order, **kwargs):
        _flip_roll_to_absent(hearing, staff)  # commits after the snapshot, before the render
        return real_render(order, **kwargs)

    monkeypatch.setattr(rendering, "page_facts", facts)
    monkeypatch.setattr(rendering, "render_pdf", render_after_an_edit)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.start_signing(ready.pk, actor=signer)
    monkeypatch.setattr(rendering, "render_pdf", real_render)
    mark_roll(hearing, staff)  # the edit is reverted before confirmation

    snapshot = Order.objects.get(pk=ready.pk).signing_attendance
    assert snapshot and all("was present" in line for line in snapshot)
    assert printed == [snapshot]
    signed = signing.record_signature(ready.pk, success(ready, signer).pk, actor=signer)
    assert signed.is_signed and signed.signing_attendance == printed[0]
