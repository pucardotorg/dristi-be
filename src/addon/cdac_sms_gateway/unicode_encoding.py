"""Numeric HTML-entity encoding for the CDAC unicode endpoint."""


def is_unicode_content(text: str) -> bool:
    """Return True when the text contains any code point above ASCII."""

    return any(ord(character) > 127 for character in text)


def to_html_entities(text: str) -> str:
    """Encode every code point as a numeric HTML entity.

    ASCII characters are encoded too: the CDAC unicode endpoint expects numeric
    entities for the whole body rather than raw UTF-8.
    """

    return "".join(f"&#{ord(character)};" for character in text)
