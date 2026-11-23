"""Drafting (spec 0039 #5): create, text, title, type, links and discard."""

import uuid

import pytest
from rest_framework.exceptions import NotFound, ValidationError

from apps.api.errors import BusinessError
from apps.core.models import Configuration
from apps.hearings.enums import HearingStatus, ReleaseReason
from apps.hearings.models import Hearing
from apps.orders.enums import ItemSource, OrderStatus
from apps.orders.models import Order
from apps.orders.services import drafting, items

from .factories import TODAY, code, make_case, schedule, started_hearing

pytestmark = pytest.mark.django_db


@pytest.fixture
def hearing(case, staff):
    return started_hearing(case, staff)


@pytest.fixture
def order(hearing, drafter):
    return drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter)[0]


def test_a_hearing_has_one_draft_and_a_second_create_returns_it(hearing, drafter):
    first, created = drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter)
    again, created_again = drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter)
    assert created and not created_again
    assert first.pk == again.pk
    assert first.hearing_id == hearing.pk
    assert Order.objects.filter(hearing_id=hearing.pk).count() == 1
    assert Hearing.objects.get(pk=hearing.pk).order_id == first.pk


def test_a_hearing_order_takes_its_case_and_court_from_the_hearing(order, case):
    assert order.case_id == case.pk
    assert order.court_id == case.court_id
    assert order.status == OrderStatus.DRAFT
    assert order.order_type.code == "NORMAL"
    assert order.title == "Order"


def test_no_order_before_the_hearing_starts(case, drafter):
    scheduled = schedule(case, TODAY)
    with pytest.raises(BusinessError) as excinfo:
        drafting.create_in_hearing(hearing_id=scheduled.pk, actor=drafter)
    assert code(excinfo) == "E14004"


def test_unknown_hearing_is_not_found(drafter):
    with pytest.raises(NotFound):
        drafting.create_in_hearing(hearing_id=uuid.uuid4(), actor=drafter)


def test_several_drafts_may_stand_open_on_a_case_outside_a_hearing(case, drafter):
    one = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    two = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    assert one.pk != two.pk
    assert one.hearing_id is None


def test_a_case_not_in_a_courtroom_takes_no_order(drafter, courtroom):
    unregistered = make_case(courtroom, status="PENDING_REGISTRATION")
    with pytest.raises(BusinessError) as excinfo:
        drafting.create_outside_hearing(case_id=unregistered.pk, actor=drafter)
    assert code(excinfo) == "E14003"


def test_an_outside_order_starts_from_the_listed_hearing(case, drafter):
    scheduled = schedule(case, TODAY, "EVIDENCE_OF_COMPLAINANT")
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    assert order.next_hearing_state == "LISTED"
    assert order.next_hearing_date == scheduled.hearing_date
    assert order.next_hearing_purpose == "EVIDENCE_OF_COMPLAINANT"
    assert order.next_hearing_held is False


# -- presets ----------------------------------------------------------------------


def test_the_take_cognizance_preset_adds_removable_preset_items(case, drafter, filler):
    order = drafting.create_outside_hearing(
        case_id=case.pk,
        actor=drafter,
        preset={"kind": "COGNIZANCE", "action": "TAKE_COGNIZANCE"},
    )
    rows = list(order.items.order_by("position"))
    assert [row.item_type.code for row in rows] == ["COGNIZANCE", "ISSUE_OF_SUMMONS"]
    assert {row.added_by_source for row in rows} == {ItemSource.PRESET}
    items.remove(order.pk, rows[1].pk, actor=filler)
    assert order.items.count() == 1


def test_a_cognizance_preset_adds_delay_acceptance_only_when_delay_applies(
    case, drafter, monkeypatch
):
    monkeypatch.setattr("apps.cases.selectors.delay_applicable", lambda case_id: False)
    order = drafting.create_outside_hearing(
        case_id=case.pk,
        actor=drafter,
        preset={
            "kind": "COGNIZANCE",
            "action": "TAKE_COGNIZANCE",
            "delay_application_id": str(uuid.uuid4()),
        },
    )
    assert "ACCEPT_APPLICATION" not in [row.item_type.code for row in order.items.all()]
    monkeypatch.setattr("apps.cases.selectors.delay_applicable", lambda case_id: True)
    order = drafting.create_outside_hearing(
        case_id=case.pk,
        actor=drafter,
        preset={
            "kind": "COGNIZANCE",
            "action": "TAKE_COGNIZANCE",
            "delay_application_id": str(uuid.uuid4()),
        },
    )
    assert [row.item_type.code for row in order.items.order_by("position")][
        0
    ] == "ACCEPT_APPLICATION"


def test_an_application_preset_adds_the_matching_item_with_its_target(case, drafter):
    application = uuid.uuid4()
    order = drafting.create_outside_hearing(
        case_id=case.pk,
        actor=drafter,
        preset={"kind": "APPLICATION", "action": "REJECT", "application_id": str(application)},
    )
    (item,) = order.items.all()
    assert item.item_type.code == "REJECT_APPLICATION"
    assert item.target_id == application
    assert item.target_type == "APPLICATION"


def test_a_failing_preset_leaves_no_order_behind(case, drafter):
    before = Order.objects.count()
    with pytest.raises(ValidationError):
        drafting.create_outside_hearing(
            case_id=case.pk, actor=drafter, preset={"kind": "APPLICATION", "action": "ACCEPT"}
        )
    assert Order.objects.count() == before


# -- text --------------------------------------------------------------------------


def test_text_is_sanitised_to_the_allow_list(order, drafter):
    drafting.edit_text(
        order.pk,
        '<p onclick="x">Heard.<script>alert(1)</script></p><ol type="a"><li>one</li></ol>'
        '<a href="http://evil">link</a>',
        actor=drafter,
    )
    order.refresh_from_db()
    assert "script" not in order.text and "onclick" not in order.text and "href" not in order.text
    assert '<ol type="a"><li>one</li></ol>' in order.text
    assert "<p>Heard.</p>" in order.text


def test_saving_the_same_text_does_not_bump_the_version(order, drafter):
    drafting.edit_text(order.pk, "<p>Heard.</p>", actor=drafter)
    order.refresh_from_db()
    version = order.text_version
    drafting.edit_text(order.pk, "<p>Heard.</p>", actor=drafter)
    order.refresh_from_db()
    assert order.text_version == version == 1


def test_a_stale_text_version_is_refused_and_data_has_its_own(order, drafter, filler):
    drafting.edit_text(order.pk, "<p>One.</p>", actor=drafter, text_version=0)
    with pytest.raises(BusinessError) as excinfo:
        drafting.edit_text(order.pk, "<p>Two.</p>", actor=drafter, text_version=0)
    assert code(excinfo) == "E14002"
    # An order data write against the data version is not blocked by a text change.
    items.add(order.pk, "COGNIZANCE", actor=filler, data_version=0)


def test_text_over_the_limit_is_refused(order, drafter):
    Configuration.objects.update_or_create(
        config_set="orders", config_key="text_max_bytes", defaults={"config_value": "20"}
    )
    with pytest.raises(BusinessError) as excinfo:
        drafting.edit_text(order.pk, "<p>" + "x" * 50 + "</p>", actor=drafter)
    assert code(excinfo) == "E14020"


def test_a_text_change_reopens_complete_order_data(order, drafter):
    Order.objects.filter(pk=order.pk).update(data_complete=True)
    drafting.edit_text(order.pk, "<p>New.</p>", actor=drafter)
    order.refresh_from_db()
    assert order.data_complete is False


def test_text_cannot_be_edited_once_sent_for_signing(order, drafter):
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.SENT_FOR_SIGNING)
    with pytest.raises(BusinessError) as excinfo:
        drafting.edit_text(order.pk, "<p>x</p>", actor=drafter)
    assert code(excinfo) == "E14001"


# -- title -----------------------------------------------------------------------


def test_the_default_title_follows_the_items_until_edited(order, filler, drafter):
    assert order.title == "Order"
    items.add(order.pk, "COGNIZANCE", actor=filler)
    order.refresh_from_db()
    assert order.title == "Cognizance"
    items.add(order.pk, "ISSUE_OF_SUMMONS", actor=filler)
    order.refresh_from_db()
    assert order.title == "Cognizance and other items"
    drafting.edit_title(order.pk, "My own title", actor=drafter)
    items.add(order.pk, "COST", actor=filler)
    order.refresh_from_db()
    assert order.title == "My own title"
    assert order.title_overridden is True


def test_removing_every_item_returns_the_type_default_title(order, filler):
    item = items.add(order.pk, "COGNIZANCE", actor=filler)
    items.remove(order.pk, item.pk, actor=filler)
    order.refresh_from_db()
    assert order.title == "Order"


# -- type ---------------------------------------------------------------------------


def test_kerala_offers_only_normal(order, drafter):
    with pytest.raises(BusinessError) as excinfo:
        drafting.change_type(order.pk, "ROZNAMA", actor=drafter)
    assert code(excinfo) == "E14024"


@pytest.fixture
def gujarat(settings):
    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "GJ"}
    )


def test_gujarat_preselects_roznama_from_a_hearing(gujarat, hearing, drafter):
    order = drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter)[0]
    assert order.order_type.code == "ROZNAMA"
    assert order.title == "Roznama"


def test_gujarat_outside_a_hearing_is_normal_unless_taking_an_application_on_file(
    gujarat, case, drafter
):
    plain = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    assert plain.order_type.code == "NORMAL"
    onboarding = drafting.create_outside_hearing(
        case_id=case.pk,
        actor=drafter,
        preset={
            "kind": "APPLICATION",
            "action": "ACCEPT",
            "application_id": str(uuid.uuid4()),
            "onboarding": True,
        },
    )
    assert onboarding.order_type.code == "ROZNAMA"
    explicit = drafting.create_outside_hearing(
        case_id=case.pk,
        actor=drafter,
        order_type_code="NORMAL",
        preset={
            "kind": "APPLICATION",
            "action": "ACCEPT",
            "application_id": str(uuid.uuid4()),
            "onboarding": True,
        },
    )
    assert explicit.order_type.code == "NORMAL"


def test_changing_to_a_type_without_links_needs_confirmation(gujarat, case, drafter, monkeypatch):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    document_id = uuid.uuid4()
    monkeypatch.setattr(
        "apps.cases.selectors.case_documents",
        lambda case_id: [type("D", (), {"id": document_id, "name": "Vakalatnama"})()],
    )
    drafting.link_document(order.pk, document_id, actor=drafter)
    with pytest.raises(BusinessError) as excinfo:
        drafting.change_type(order.pk, "ROZNAMA", actor=drafter)
    assert code(excinfo) == "E14025"
    assert order.linked_documents.count() == 1
    drafting.change_type(order.pk, "ROZNAMA", actor=drafter, remove_linked_documents=True)
    order.refresh_from_db()
    assert order.order_type.code == "ROZNAMA"
    assert order.linked_documents.count() == 0
    with pytest.raises(BusinessError) as excinfo:
        drafting.link_document(order.pk, document_id, actor=drafter)
    assert code(excinfo) == "E14023"


def test_a_document_not_in_the_case_file_cannot_be_linked(order, drafter):
    with pytest.raises(BusinessError) as excinfo:
        drafting.link_document(order.pk, uuid.uuid4(), actor=drafter)
    assert code(excinfo) == "E14021"


def test_changing_the_type_clears_an_allotted_number(gujarat, case, drafter):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    Order.objects.filter(pk=order.pk).update(number="C/ORD/1/2026")
    drafting.change_type(order.pk, "ROZNAMA", actor=drafter)
    order.refresh_from_db()
    assert order.number == ""


# -- discard ----------------------------------------------------------------------


def test_discarding_releases_the_held_date_and_frees_the_hearing(hearing, order, drafter, setter):
    from apps.orders.services import next_hearing

    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=19), purpose="APPEARANCE", actor=setter
    )
    held = Hearing.objects.get(source_order_id=order.pk)
    assert held.status == HearingStatus.PROVISIONAL
    drafting.discard(order.pk, actor=drafter)
    order.refresh_from_db()
    held.refresh_from_db()
    assert order.status == OrderStatus.DISCARDED
    assert held.status == HearingStatus.RELEASED
    assert held.release_reason == ReleaseReason.DRAFT_DISCARDED
    assert Hearing.objects.get(pk=hearing.pk).order_id is None
    replacement, created = drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter)
    assert created and replacement.pk != order.pk


def test_only_a_draft_can_be_discarded(order, drafter):
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.SENT_FOR_SIGNING)
    with pytest.raises(BusinessError) as excinfo:
        drafting.discard(order.pk, actor=drafter)
    assert code(excinfo) == "E14001"
    assert "can:" in str(excinfo.value.detail)
