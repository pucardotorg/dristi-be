"""The *Application details* sanitiser (spec 0033 #3.3.1).

Bold, italic, underline, bulleted and numbered lists and alignment survive;
everything else is stripped, never trusted from the client. The same allow-list
is what the templates render.
"""

import re
from html import unescape

import nh3

TAGS = {"p", "br", "strong", "em", "u", "ol", "ul", "li"}
ATTRIBUTES = {"p": {"style"}, "li": {"style"}}
ALIGNMENT = re.compile(r"^\s*text-align\s*:\s*(left|center|right|justify)\s*;?\s*$", re.I)


def _filter(tag, attribute, value):
    """Keep ``style`` only as a single ``text-align``; drop every other declaration."""
    if attribute != "style":
        return None
    for declaration in value.split(";"):
        match = ALIGNMENT.match(declaration)
        if match:
            return f"text-align: {match.group(1).lower()}"
    return None


def sanitise(html: str) -> str:
    """Return ``html`` reduced to the allow-list."""
    if not html:
        return ""
    return nh3.clean(
        html,
        tags=TAGS,
        attributes=ATTRIBUTES,
        attribute_filter=_filter,
        clean_content_tags={"script", "style"},
        link_rel=None,
    ).strip()


def has_text(html: str) -> bool:
    """Whether the sanitised HTML shows any text (an empty editor still emits ``<p><br></p>``)."""
    return bool(unescape(re.sub(r"<[^>]+>", "", html or "")).strip())


def to_text(html: str) -> str:
    """Plain text, one line per block, for the PDF renderer."""
    text = re.sub(r"</(p|li)>|<br\s*/?>", "\n", html or "")
    text = re.sub(r"<li[^>]*>", "• ", text)
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()
