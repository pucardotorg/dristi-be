"""One renderer for the order page and the signed PDF (spec 0039 #5.3, ``ORD-13``).

``render_page`` builds the page from the record as HTML. ``pdf_document`` builds
the same page as the block list ``apps.pdf``'s renderer draws, so the page the
court sees and the PDF that is signed are two views of one record. The heading,
the attendance lines, the next hearing line and the signature block are never
typed (``TXT-05``): only the body between them is the drafter's.
"""

import html as html_lib
import re

import nh3
from lxml import html as lxml_html

from apps.hearings import selectors as hearing_selectors
from apps.hearings.enums import AttendanceMark, AttendeeType

from .enums import NextHearingState

ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "u",
    "ol",
    "ul",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
ALLOWED_ATTRIBUTES = {"ol": {"type"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}
SPAN_RE = re.compile(r"[1-9][0-9]?")
INLINE_MARKUP = {"strong": "b", "b": "b", "em": "i", "i": "i", "u": "u"}

# The signature box, in PDF points on the last page; the page's bottom margin leaves it clear.
SIGN_PLACEHOLDER = {"page": -1, "x": 330, "y": 40, "width": 215, "height": 70}
BOTTOM_MARGIN = 150

ATTENDEE_LABELS = {
    AttendeeType.COMPLAINANT: "Complainant",
    AttendeeType.ACCUSED: "Accused",
    AttendeeType.POA_HOLDER: "PoA holder",
    AttendeeType.COMPLAINANT_ADVOCATE: "Advocate for the complainant",
    AttendeeType.ACCUSED_ADVOCATE: "Advocate for the accused",
}


def _attribute_filter(tag, attribute, value):
    if tag == "ol" and attribute == "type":
        return value if value in ("a", "1") else None
    if attribute in ("colspan", "rowspan"):
        return value if SPAN_RE.fullmatch(value) else None
    return value


def sanitize_html(text):
    """Return ``text`` reduced to the allow-list, never trusting the client (``TXT-02``)."""
    return nh3.clean(
        text or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes=set(),
        link_rel=None,
        strip_comments=True,
    ).strip()


def plain_text(text):
    """Return the visible text of ``text`` (HTML), whitespace and non-breaking spaces collapsed."""
    bare = nh3.clean(text or "", tags=set())
    return re.sub(r"[\s ]+", " ", html_lib.unescape(bare)).strip()


def is_blank(text):
    """Whether sanitised ``text`` says nothing (``SND-02``)."""
    return not plain_text(text)


# -- HTML to renderer blocks ------------------------------------------------


def _inline(element):
    """Return the element's content as renderer markup: bold, italic, underline, breaks."""
    out = [html_lib.escape(element.text or "", quote=False)]
    for child in element:
        if child.tag == "br":
            out.append("<br/>")
        else:
            inner = _inline(child)
            tag = INLINE_MARKUP.get(child.tag)
            out.append(f"<{tag}>{inner}</{tag}>" if tag else inner)
        out.append(html_lib.escape(child.tail or "", quote=False))
    return "".join(out)


def _list_block(element):
    items = [_inline(item).strip() for item in element.iterchildren("li")]
    block = {"type": "list", "items": items, "ordered": element.tag == "ol"}
    if element.tag == "ol" and element.get("type") == "a":
        block["list_type"] = "a"
    return block


def _table_block(element):
    rows = [
        [_inline(cell).strip() for cell in row if cell.tag in ("td", "th")]
        for row in element.iter("tr")
    ]
    rows = [row for row in rows if row]
    if not rows:
        return None
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return {"type": "table", "columns": [{"header": ""} for _ in range(width)], "rows": rows}


def html_to_blocks(text):
    """Turn sanitised order text into renderer blocks, in order."""
    if is_blank(text):
        return []
    root = lxml_html.fragment_fromstring(text, create_parent="div")
    blocks = []
    run = [html_lib.escape(root.text or "", quote=False)]

    def flush():
        # Consecutive top-level inline nodes and their tails are one paragraph.
        markup = "".join(run).strip()
        while markup.startswith("<br/>") or markup.endswith("<br/>"):
            markup = markup.removeprefix("<br/>").removesuffix("<br/>").strip()
        run.clear()
        if markup:
            blocks.append({"type": "paragraph", "text": markup})

    for child in root:
        if child.tag in ("ol", "ul", "table", "p"):
            flush()
            if child.tag in ("ol", "ul"):
                blocks.append(_list_block(child))
            elif child.tag == "table":
                if block := _table_block(child):
                    blocks.append(block)
            else:
                markup = _inline(child).strip()
                if markup:
                    blocks.append({"type": "paragraph", "text": markup})
        elif child.tag == "br":
            run.append("<br/>")
        else:
            inner = _inline(child)
            tag = INLINE_MARKUP.get(child.tag)
            run.append(f"<{tag}>{inner}</{tag}>" if tag else inner)
        run.append(html_lib.escape(child.tail or "", quote=False))
    flush()
    return blocks


# -- The record the page is built from ---------------------------------------


def attendance_sentences(hearing_id):
    """One line per marked person: people not required and empty lines are left out (``ATT-03``)."""
    if not hearing_id:
        return []
    lines = []
    for line in hearing_selectors.attendance_lines(hearing_id):
        if line.mark == AttendanceMark.NOT_REQUIRED:
            continue
        label = ATTENDEE_LABELS.get(line.attendee_type, line.attendee_type)
        if line.mark == AttendanceMark.PRESENT:
            how = " (by video)" if line.appearance_mode == "VIDEO" else ""
            lines.append(f"{label} {line.name} was present{how}.")
        else:
            lines.append(f"{label} {line.name} was absent.")
    return lines


def next_hearing_line(order, purpose_label=""):
    """The order's closing line about the next hearing."""
    if order.next_hearing_state == NextHearingState.LISTED and order.next_hearing_date:
        date = order.next_hearing_date.strftime("%d %B %Y").lstrip("0")
        purpose = f" for {purpose_label}" if purpose_label else ""
        return f"Next hearing: {date}{purpose}."
    if order.next_hearing_state == NextHearingState.NOT_LISTED_AGAIN:
        return "The case is not listed again."
    return ""


def signature_lines(order, *, signer_name="", signed=False):
    """The signature block: who signs and when, or that it is not signed yet.

    ``signer_name`` with ``signed`` false is the PDF being signed: the name and
    designation are printed under the empty signature box.
    """
    designation = order.signer_designation or "Magistrate"
    when = order.order_date.strftime("%d %B %Y").lstrip("0") if order.order_date else ""
    if signer_name and signed:
        return [signer_name, designation, f"Signed on {when}" if when else "Signed"]
    if signer_name:
        return [signer_name, designation, f"Date: {when}" if when else ""]
    return [designation, "Not signed"]


def page_facts(order, *, case_summary=None, purpose_label="", signing_user=None, number=None):
    """Gather everything the page shows, once, so HTML and PDF cannot differ.

    ``signing_user`` is the person about to sign: their name goes on the document
    being signed. ``number`` replaces the order's own (a Roznama's internal number).
    """
    signer = ""
    if signing_user is not None:
        signer = signing_user.name or ""
    elif order.signed_by_id:
        signer = order.signed_by.name or ""
    return {
        # A signed order keeps the heading its signing file was prepared with.
        "heading": (order.is_signed and order.signing_heading) or order.order_type.pdf_heading,
        "court": order.court.name,
        "number": order.number if number is None else number,
        "date": order.order_date.strftime("%d %B %Y").lstrip("0") if order.order_date else "",
        "case_number": case_summary.display_number if case_summary else "",
        "case_title": case_summary.title if case_summary else "",
        "title": order.title,
        # A signed order keeps the roll its signing file was prepared with.
        "attendance": (
            order.signing_attendance if order.is_signed else attendance_sentences(order.hearing_id)
        ),
        "body": order.text,
        "next_hearing": next_hearing_line(order, purpose_label),
        "signature": signature_lines(
            order, signer_name=signer, signed=order.is_signed and signing_user is None
        ),
    }


def _e(value):
    return html_lib.escape(str(value or ""), quote=True)


def render_page(order, *, case_summary=None, purpose_label=""):
    """Return the page as HTML: the one thing the screen and the PDF both show (``ORD-13``)."""
    facts = page_facts(order, case_summary=case_summary, purpose_label=purpose_label)
    parts = ['<section class="order-page">', f'<header><p class="court">{_e(facts["court"])}</p>']
    if facts["case_number"] or facts["case_title"]:
        parts.append(f'<p class="case">{_e(facts["case_number"])} · {_e(facts["case_title"])}</p>')
    parts.append(f"<h1>{_e(facts['heading'])}</h1>")
    if facts["number"]:
        parts.append(f'<p class="number">{_e(facts["number"])} · {_e(facts["date"])}</p>')
    parts.append("</header>")
    if facts["attendance"]:
        parts.append(
            '<div class="attendance">'
            + "".join(f"<p>{_e(line)}</p>" for line in facts["attendance"])
            + "</div>"
        )
    parts.append(f'<div class="body">{facts["body"]}</div>')
    if facts["next_hearing"]:
        parts.append(f'<p class="next-hearing">{_e(facts["next_hearing"])}</p>')
    parts.append(
        '<footer class="signature">'
        + "".join(f"<p>{_e(line)}</p>" for line in facts["signature"])
        + "</footer></section>"
    )
    return "".join(parts)


def pdf_document(
    order,
    *,
    case_summary=None,
    purpose_label="",
    entry_text=None,
    heading=None,
    signing_user=None,
    number=None,
):
    """Return the order as a renderer document: the same facts as ``render_page``.

    ``entry_text`` (sanitised HTML) replaces the body, and ``heading`` the
    heading, for a Gujarat Roznama (#8.4), which prints the diary entry. The
    entry is complete as composed, so the attendance and next hearing lines are
    not added around it.
    """
    facts = page_facts(
        order,
        case_summary=case_summary,
        purpose_label=purpose_label,
        signing_user=signing_user,
        number=number,
    )
    body = facts["body"] if entry_text is None else entry_text
    blocks = [
        {
            "type": "paragraph",
            "text": html_lib.escape(facts["court"]),
            "align": "center",
            "style": "heading3",
        },
        {
            "type": "heading",
            "text": html_lib.escape(heading or facts["heading"]),
            "level": 1,
            "align": "center",
        },
    ]
    if facts["number"]:
        blocks.append(
            {
                "type": "paragraph",
                "text": html_lib.escape(f"{facts['number']} · {facts['date']}"),
                "align": "center",
            }
        )
    if facts["case_number"] or facts["case_title"]:
        blocks.append(
            {
                "type": "paragraph",
                "text": html_lib.escape(f"{facts['case_number']} · {facts['case_title']}"),
                "align": "center",
            }
        )
    blocks.append({"type": "line"})
    if entry_text is None:
        blocks += [
            {"type": "paragraph", "text": html_lib.escape(line)} for line in facts["attendance"]
        ]
    blocks += html_to_blocks(body)
    if entry_text is None and facts["next_hearing"]:
        blocks.append({"type": "paragraph", "text": html_lib.escape(facts["next_hearing"])})
    blocks.append({"type": "spacer", "height": 18})
    for line in facts["signature"]:
        blocks.append({"type": "paragraph", "text": html_lib.escape(line), "align": "right"})
    return {
        "page": {"size": "A4", "margins": {"bottom": BOTTOM_MARGIN}},
        "metadata": {"title": facts["title"] or facts["heading"]},
        "sections": [blocks],
    }


def render_pdf(order, **kwargs):
    """Render the order's PDF in-process (spec 0016 renderer, no HTTP)."""
    from apps.pdf.renderer import get_renderer

    return get_renderer().render(pdf_document(order, **kwargs), {})
