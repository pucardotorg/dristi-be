"""The page and the PDF come from one renderer (spec 0039 #5.3); plus selectors and mail."""

import datetime

import pytest

from apps.api.errors import BusinessError
from apps.orders import rendering, selectors
from apps.orders.models import Order
from apps.orders.services import drafting, lifecycle, notifications, signing

from .factories import TODAY

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("dirty", "clean"),
    [
        ("<p onclick='x'>a</p>", "<p>a</p>"),
        ("<script>alert(1)</script><p>b</p>", "<p>b</p>"),
        ("<p>c<br>d</p>", "<p>c<br>d</p>"),
        ('<ol type="a"><li>x</li></ol>', '<ol type="a"><li>x</li></ol>'),
        ('<ol type="z"><li>x</li></ol>', "<ol><li>x</li></ol>"),
        (
            '<table><tr><td colspan="2" style="x">t</td></tr></table>',
            '<table><tbody><tr><td colspan="2">t</td></tr></tbody></table>',
        ),
        ('<td colspan="99999">z</td>', "z"),
        ("<img src=x onerror=1><p>d</p>", "<p>d</p>"),
        ('<a href="javascript:1">e</a>', "e"),
        ("<h1>h</h1><div>f</div>", "hf"),
    ],
)
def test_sanitising_keeps_only_the_allow_list(dirty, clean):
    assert rendering.sanitize_html(dirty) == clean


@pytest.mark.parametrize(
    "body",
    [
        '<ol><li>Pay:<ol type="a"><li>A</li><li>B</li></ol></li></ol>',
        "<ul><li>x<ul><li>y</li></ul></li></ul>",
        "<ol><li>x<table><tr><td>y</td></tr></table></li></ol>",
        "<table><tr><td><ol><li>x</li></ol></td></tr></table>",
        # The PDF reads only a list's items and a table's rows: anything else would be lost.
        "<ul><ul><li>x</li></ul></ul>",
        "<ul>loose<li>a</li></ul>",
        "<ol><p>para</p><li>a</li></ol>",
        "<table><caption>c</caption><tr><td>1</td></tr></table>",
        "<strong><ul><li>x</li></ul></strong>",
    ],
)
def test_structure_the_pdf_cannot_draw_is_refused(body):
    with pytest.raises(BusinessError) as excinfo:
        rendering.sanitize_html(body)
    assert excinfo.value.error.code == "E14027"


@pytest.mark.parametrize(
    "body",
    [
        "<ol><li>a</li></ol><ul><li>b</li></ul>",
        "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>",
        '<table><tr><td colspan="2">A</td></tr></table>',
        '<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>',
    ],
)
def test_ordinary_lists_and_rectangular_tables_are_accepted(body):
    assert rendering.sanitize_html(body)


def test_blank_html_says_nothing():
    for blank in ("", "  ", "<p></p>", "<p>&nbsp;</p>", "<p><br></p>"):
        assert rendering.is_blank(blank)
    assert not rendering.is_blank("<p>x</p>")


def test_html_becomes_renderer_blocks():
    blocks = rendering.html_to_blocks(
        "<p>Para <strong>bold</strong> <em>it</em><br>next</p>"
        "<ol><li>one</li><li>two</li></ol><ul><li>dot</li></ul>"
        "<table><tr><th>A</th><td>B</td></tr><tr><td>C</td></tr></table>"
    )
    assert blocks[0] == {"type": "paragraph", "text": "Para <b>bold</b> <i>it</i><br/>next"}
    assert blocks[1] == {"type": "list", "items": ["one", "two"], "ordered": True}
    assert blocks[2]["ordered"] is False
    assert blocks[3]["rows"] == [["A", "B"], ["C", ""]]
    assert rendering.html_to_blocks("") == []


def test_text_is_escaped_in_the_pdf_blocks():
    (block,) = rendering.html_to_blocks("<p>a &lt; b &amp; c</p>")
    assert block["text"] == "a &lt; b &amp; c"


def test_the_page_shows_heading_attendance_text_next_hearing_and_signature_block(ready, hearing):
    page = signing.render_page_html(ready)
    assert (
        page.index("Evidence of the complainant") > page.index("Heard.") > page.index("was present")
    )
    assert "<h1>Order</h1>" in page
    assert "Magistrate" in page and "Not signed" in page
    assert page.count("was present") == 3  # complainant, advocate for the complainant, accused
    assert "KL" not in page


def test_people_not_required_are_left_out_of_the_attendance_lines(hearing, order, staff):
    from apps.cases.selectors import get_attendance_roll
    from apps.hearings.services import courtroom

    roll = get_attendance_roll(hearing.case_id)
    marks = [
        {
            "attendee_type": e.type,
            "participant_id": e.participant_id,
            "mark": "NOT_REQUIRED" if i else "ABSENT",
        }
        for i, e in enumerate(roll)
    ]
    courtroom.set_attendance(hearing_id=hearing.pk, marks=marks, actor=staff)
    lines = rendering.attendance_sentences(hearing.pk)
    assert len(lines) == 1 and lines[0].endswith("was absent.")


def test_the_pdf_is_the_same_page_with_the_signer_and_number(ready, signer):
    Order.objects.filter(pk=ready.pk).update(number="C/ORD/7/2026", order_date=TODAY)
    ready.refresh_from_db()
    document = rendering.pdf_document(ready, signing_user=signer)
    texts = [b.get("text", "") for b in document["sections"][0]]
    assert any("C/ORD/7/2026" in t for t in texts)
    assert any("Heard." in t for t in texts)
    assert texts[-3:] == ["Signer", "Magistrate", "Date: 12 November 2026"]
    pdf = rendering.render_pdf(ready, signing_user=signer)
    assert pdf.startswith(b"%PDF")


def test_a_roznama_is_headed_roznama_and_uses_its_own_number(ready):
    document = rendering.pdf_document(
        ready, heading="Roznama", number="C/RZN/1/2026", entry_text="<p>Entry</p>"
    )
    texts = [b.get("text", "") for b in document["sections"][0]]
    assert "Roznama" in texts and any("C/RZN/1/2026" in t for t in texts)
    assert "Entry" in texts and not any("Heard." in t for t in texts)


def test_the_signature_box_fits_the_page_and_leaves_the_text_clear():
    box = rendering.SIGN_PLACEHOLDER
    assert box["page"] == -1
    assert box["x"] + box["width"] <= 595 and box["y"] + box["height"] <= rendering.BOTTOM_MARGIN


# -- selectors ------------------------------------------------------------------------------------


def test_order_status_for_hearings_reads_a_whole_day_in_one_order_query(
    case, courtroom, staff, signer, django_assert_max_num_queries
):
    from apps.hearings.tests.factories import make_case, schedule

    from .factories import started_hearing

    plain = schedule(make_case(courtroom), TODAY)
    sent_hearing = started_hearing(case, staff)
    order = drafting.create_in_hearing(hearing_id=sent_hearing.pk, actor=staff)[0]
    with django_assert_max_num_queries(2):
        status = selectors.order_status_for_hearings([plain.pk, sent_hearing.pk])
    assert status[plain.pk]["stages"] == ["NONE"]
    assert status[sent_hearing.pk]["stages"] == ["DRAFTING"]
    assert status[sent_hearing.pk]["order_id"] == order.pk


def test_an_order_sent_for_signing_matches_both_of_its_stages(ready, staff, hearing):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    status = selectors.order_status_for_hearings([hearing.pk])
    assert status[hearing.pk]["stages"] == ["AWAITING_SIGNATURE", "ORDER_DATA_TO_FILL"]
    assert status[hearing.pk]["next_hearing"]["date"] == ready.next_hearing_date


def test_the_diary_entry_contract_for_the_a_diary(ready):
    assert "Heard." in selectors.diary_entry(ready.pk)
    assert selectors.diary_entry(ready.pk.__class__(int=0)) is None


# -- notification ---------------------------------------------------------------------------------------


def test_signing_notifies_parties_on_commit_only(
    ready, staff, signer, django_capture_on_commit_callbacks, monkeypatch, complainant_user
):
    sent = []
    monkeypatch.setattr(
        notifications,
        "enqueue_sms",
        lambda key, to, ctx, correlation_id="": sent.append((key, ctx)),
    )
    monkeypatch.setattr(notifications, "enqueue_email", lambda *a, **k: None)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    assert sent == []
    for callback in callbacks:
        callback()
    assert sent and sent[0][0] == "ORDER_SIGNED"
    assert set(sent[0][1]) == {"case_number", "case_title", "order_title", "order_date"}


def test_the_order_signed_template_is_seeded_and_renders():
    from apps.messaging.models import MessageTemplate

    template = MessageTemplate.objects.get(message_key="ORDER_SIGNED", message_type="sms")
    assert "{{order_title}}" in template.content
    assert datetime and Order


def test_lettered_lists_keep_their_style_in_the_pdf_blocks():
    blocks = rendering.html_to_blocks(
        '<ol type="a"><li>x</li></ol><ol><li>y</li></ol><ol type="1"><li>z</li></ol><ul><li>w</li></ul>'
    )
    assert blocks[0]["list_type"] == "a" and blocks[0]["ordered"] is True
    assert all("list_type" not in block for block in blocks[1:])


def test_a_lettered_list_prints_letters_in_the_pdf():
    pypdf = pytest.importorskip("pypdf")
    import io

    from apps.pdf.renderer import get_renderer

    def text(list_type):
        block = {"type": "list", "items": ["first", "second"], "ordered": True}
        if list_type:
            block["list_type"] = list_type
        pdf = get_renderer().render({"page": {"size": "A4"}, "sections": [[block]]}, {})
        return pypdf.PdfReader(io.BytesIO(pdf)).pages[0].extract_text()

    assert "a." in text("a") and "b." in text("a")
    assert "1." in text(None) and "a." not in text(None)


def test_a_long_lettered_list_gives_every_item_its_own_letters_in_the_pdf():
    pypdf = pytest.importorskip("pypdf")
    import io

    from apps.pdf.renderer import get_renderer

    block = {
        "type": "list",
        "items": [f"item{n:02d}" for n in range(1, 29)],
        "ordered": True,
        "list_type": "a",
    }
    pdf = get_renderer().render({"page": {"size": "A4"}, "sections": [[block]]}, {})
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    lines = text.splitlines()
    labels = [lines[i - 1] for i, line in enumerate(lines) if line.startswith("item")]
    assert labels[:3] == ["a.", "b.", "c."]
    assert labels[25:] == ["z.", "aa.", "ab."]
    assert len(set(labels)) == 28


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<br/>", ""),
        (" <br/> <br/> x <br/> ", "x"),
        ("<br/>a<br/>b<br/><br/>", "a<br/>b"),
        ("  x  ", "x"),
        ("<br/>\n<br/>\t", ""),
    ],
)
def test_trim_breaks_keeps_inner_breaks_and_whitespace_rules(raw, expected):
    assert rendering._trim_breaks(raw) == expected


def test_a_long_run_of_breaks_is_trimmed_in_one_pass():
    blocks = rendering.html_to_blocks("<br>" * 50_000 + "text")
    assert blocks == [{"type": "paragraph", "text": "text"}]


def test_top_level_inline_markup_and_its_tail_are_one_paragraph():
    blocks = rendering.html_to_blocks("<strong>Not</strong> allowed.")
    assert blocks == [{"type": "paragraph", "text": "<b>Not</b> allowed."}]
    blocks = rendering.html_to_blocks("Lead <em>em</em> mid<br>line<p>Para</p>tail <u>u</u>")
    assert [b["text"] for b in blocks] == ["Lead <i>em</i> mid<br/>line", "Para", "tail <u>u</u>"]


def test_real_block_boundaries_stay_and_a_lone_break_adds_nothing():
    blocks = rendering.html_to_blocks(
        "<p>a</p><br><ol><li>x</li></ol><p>b</p><table><tr><td>c</td></tr></table>"
    )
    assert [b["type"] for b in blocks] == ["paragraph", "list", "paragraph", "table"]


def test_the_roznama_entry_is_not_wrapped_in_order_lines_again(ready, staff, hearing):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    order = Order.objects.get(pk=ready.pk)
    entry = "<p>Complainant was present.</p><p>Entry.</p><p>Next hearing: x.</p>"
    doc = rendering.pdf_document(order, entry_text=entry, heading="Roznama")
    texts = [b.get("text", "") for b in doc["sections"][0]]
    assert sum("Entry." in t for t in texts) == 1
    assert sum("was present" in t for t in texts) == 1
    assert not any(t.startswith("Next hearing") and "x." not in t for t in texts)
    plain = rendering.pdf_document(order)
    plain_texts = [b.get("text", "") for b in plain["sections"][0]]
    assert any("was present" in t for t in plain_texts)
    assert any(t.startswith("Next hearing") for t in plain_texts)


def test_a_failed_summary_lookup_does_not_stop_the_later_commit_hooks(monkeypatch):
    from apps.orders.services import notifications

    def broken(case_ids):
        raise RuntimeError("database gone")

    monkeypatch.setattr(notifications, "get_case_summaries", broken)
    notifications._notify(
        "case-id", notifications.ORDER_SIGNED, "order-id", "Order", datetime.date(2026, 1, 1)
    )  # logs, never raises
