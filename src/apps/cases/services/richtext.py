"""Rich-text editor output as safe paragraphs for the complaint PDF.

The affidavit, a party-in-person affidavit and the relief fields are stored as
the editor sent them (``models.Case.affidavit``: "sanitized wherever it is
rendered"). The PDF renderer accepts only a small inline markup, and must never
receive markup a user wrote, so the HTML is rebuilt here from a whitelist:
paragraphs, line breaks, bold, italic, underline and lists, kept as the user
left them (efiling ``DOC-04``). Every other tag is dropped and its text kept;
every text is escaped.
"""

from html import escape
from html.parser import HTMLParser

_INLINE = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u"}
_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"}
_LISTS = {"ol", "ul"}
# Their content is never text to print.
_SKIPPED = {"script", "style", "head", "title"}


class _Converter(HTMLParser):
    """Collect paragraphs of safe inline markup from editor HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.current: list[str] = []
        self.open: list[str] = []
        self.lists: list[list] = []  # [kind, counter] per open list
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED:
            self.skipping += 1
        elif tag in _INLINE:
            self.current.append(f"<{_INLINE[tag]}>")
            self.open.append(_INLINE[tag])
        elif tag == "br":
            self.current.append("<br/>")
        elif tag in _LISTS:
            self._flush()
            self.lists.append([tag, 0])
        elif tag in _BLOCK:
            self._flush()
            if tag == "li" and self.lists:
                kind = self.lists[-1]
                kind[1] += 1
                indent = "&nbsp;" * 4 * len(self.lists)
                marker = f"{kind[1]}." if kind[0] == "ol" else "&#8226;"
                self.current.append(f"{indent}{marker} ")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.current.append("<br/>")

    def handle_endtag(self, tag):
        if tag in _SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _INLINE:
            name = _INLINE[tag]
            if name in self.open:
                # Close in nesting order so the markup stays well formed.
                while self.open:
                    closing = self.open.pop()
                    self.current.append(f"</{closing}>")
                    if closing == name:
                        break
        elif tag in _LISTS:
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.skipping:
            self.current.append(escape(data, quote=False))

    def _flush(self):
        # Formatting left open by the editor ends with its paragraph.
        text = "".join(self.current) + "".join(f"</{name}>" for name in reversed(self.open))
        self.current, self.open = [], []
        if _visible(text):
            self.paragraphs.append(text)

    def close(self):
        super().close()
        self._flush()


def _visible(markup):
    """Whether ``markup`` shows any text once rendered."""
    stripped = markup
    for token in ("<br/>", "<b>", "</b>", "<i>", "</i>", "<u>", "</u>", "&nbsp;"):
        stripped = stripped.replace(token, "")
    return bool(stripped.strip())


def to_paragraphs(html):
    """Return ``html`` as a list of safe paragraphs; ``[]`` when it shows no text."""
    if not html:
        return []
    converter = _Converter()
    converter.feed(str(html))
    converter.close()
    return converter.paragraphs
