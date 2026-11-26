"""The diary entry (spec 0039 #6.6): composed on read, per-state rules, the A-Diary path."""

import pytest
from rest_framework.exceptions import ValidationError

from apps.api.errors import BusinessError
from apps.core.models import Configuration
from apps.orders import selectors
from apps.orders.models import Order
from apps.orders.services import diary, drafting, lifecycle, next_hearing, signing

from .factories import TODAY, code

pytestmark = pytest.mark.django_db


def state(value):
    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": value}
    )


def triggered(case, staff, signer, type_code="NORMAL", text="<p>Heard the parties.</p>"):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code=type_code)
    drafting.edit_text(order.pk, text, actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.mark_complete(order.pk, actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    signing.record_signed_file(order.pk, "signed", "DSC", actor=signer)
    return Order.objects.get(pk=order.pk)


def test_the_entry_is_the_order_text_with_attendance_and_next_hearing_lines_in_full(ready, hearing):
    entry = diary.composed_entry(ready)
    assert "was present" in entry
    assert "<p>Heard. Called again on the next date.</p>" in entry
    assert "Next hearing: 19 November 2026 for Evidence of the complainant." in entry
    assert entry.index("was present") < entry.index("Heard.") < entry.index("Next hearing")


def test_a_separate_entry_is_kept_as_written_and_the_text_is_untouched(ready, staff):
    diary.set_entry(ready.pk, same_as_text=False, text="<p>Short summary.</p>", actor=staff)
    ready.refresh_from_db()
    assert diary.composed_entry(ready) == "<p>Short summary.</p>"
    assert ready.text == "<p>Heard. Called again on the next date.</p>"
    # Switching back keeps the typed text for later.
    diary.set_entry(ready.pk, same_as_text=True, actor=staff)
    ready.refresh_from_db()
    assert ready.diary_text == "<p>Short summary.</p>"
    assert "Heard." in diary.composed_entry(ready)


def test_a_separate_entry_cannot_be_blank(ready, staff):
    with pytest.raises(ValidationError) as excinfo:
        diary.set_entry(ready.pk, same_as_text=False, text="<p> </p>", actor=staff)
    assert excinfo.value.detail["text"][0].code == "E14011"


def test_the_entry_is_labelled_per_state(case, staff):
    labels = {}
    for code_, label in (("KL", "A-Diary text"), ("GJ", "Roznama"), ("PH", "Summary")):
        state(code_)
        order = drafting.create_outside_hearing(
            case_id=case.pk, actor=staff, order_type_code="NORMAL"
        )
        labels[code_] = selectors.order_detail(order, frozenset())["diary_entry"]["label"]
        assert labels[code_] == label


def test_a_roznama_type_order_refuses_a_separate_entry(case, staff):
    state("GJ")
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code="ROZNAMA")
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry(order.pk, same_as_text=False, text="<p>x</p>", actor=staff)
    assert code(excinfo) == "E14026"
    detail = selectors.order_detail(order, frozenset())["diary_entry"]
    assert detail["separate_allowed"] is False


def test_changing_to_roznama_makes_the_entry_the_text_and_back_restores_it(case, staff):
    state("GJ")
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code="NORMAL")
    diary.set_entry(order.pk, same_as_text=False, text="<p>Mine.</p>", actor=staff)
    drafting.change_type(order.pk, "ROZNAMA", actor=staff)
    order.refresh_from_db()
    assert diary.same_as_text(order) is True and order.diary_text == "<p>Mine.</p>"
    assert diary.composed_entry(order) != "<p>Mine.</p>"
    drafting.change_type(order.pk, "NORMAL", actor=staff)
    order.refresh_from_db()
    assert order.diary_text == "<p>Mine.</p>"
    assert diary.same_as_text(order) is False
    assert diary.composed_entry(order) == "<p>Mine.</p>"


def test_kerala_edits_after_triggering_go_through_the_a_diary_and_never_touch_the_text(
    case, staff, signer
):
    state("KL")
    order = triggered(case, staff, signer)
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry(order.pk, same_as_text=False, text="<p>x</p>", actor=staff)
    assert code(excinfo) == "E14014"
    diary.set_entry_text(order.pk, "<p>Edited in the A-Diary.</p>", staff)
    order.refresh_from_db()
    assert order.diary_same_as_text is False
    assert order.diary_text == "<p>Edited in the A-Diary.</p>"
    assert order.text == "<p>Heard the parties.</p>"


def test_the_a_diary_path_is_kerala_only_and_after_triggering_only(case, staff, signer, ready):
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry_text(ready.pk, "<p>x</p>", staff)  # not triggered
    assert code(excinfo) == "E14014"
    state("PH")
    order = triggered(case, staff, signer)
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry_text(order.pk, "<p>x</p>", staff)  # Punjab & Haryana: fixed
    assert code(excinfo) == "E14014"
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry(order.pk, same_as_text=False, text="<p>x</p>", actor=staff)
    assert code(excinfo) == "E14014"


def test_diary_entries_list_every_type_together(case, staff, signer, courtroom):
    state("GJ")
    normal = triggered(case, staff, signer, "NORMAL")
    roznama_type = triggered(case, staff, signer, "ROZNAMA", "<p>Second.</p>")
    rows = selectors.diary_entries(courtroom.pk)
    by_order = {row["order_id"]: row for row in rows}
    assert set(by_order) == {normal.pk, roznama_type.pk}
    assert by_order[normal.pk]["roznama"]["status"] == "AWAITING_SIGNATURE"
    assert by_order[roznama_type.pk]["roznama"] is None
    assert by_order[roznama_type.pk]["type"]["code"] == "ROZNAMA"
    only = selectors.diary_entries(courtroom.pk, order_type="ROZNAMA")
    assert [row["order_id"] for row in only] == [roznama_type.pk]
    assert TODAY


def test_the_case_history_shows_every_orders_entry_as_business_of_the_day(case, staff, signer):
    state("KL")
    order = triggered(case, staff, signer)
    rows = selectors.case_orders(case.pk, staff=True)
    assert rows[0]["business_of_the_day"].count("Heard the parties.") == 1
    assert rows[0]["id"] == order.pk


def test_the_entry_of_a_discarded_order_cannot_be_set(order, staff):
    drafting.discard(order.pk, actor=staff)
    with pytest.raises(BusinessError) as excinfo:
        diary.set_entry(order.pk, same_as_text=True, actor=staff)
    assert code(excinfo) == "E14001"


def test_an_a_diary_save_of_the_composed_entry_changes_nothing(case, staff, signer):
    state("KL")
    order = triggered(case, staff, signer)
    before = order.history.count()
    same = diary.set_entry_text(order.pk, diary.composed_entry(order), staff)
    same.refresh_from_db()
    assert (same.diary_same_as_text, same.diary_text) == (True, "")
    assert same.history.count() == before
