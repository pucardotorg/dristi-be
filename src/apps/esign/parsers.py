"""Parsers for the ESP callback (spec 0015 #6.3).

C-DAC posts a browser form, but deployments (and interceptors) may forward the
response document as ``application/xml`` instead. Both arrive here as a flat
mapping the provider can read; the domain never interprets the content.
"""

from rest_framework.parsers import BaseParser

# Key the raw response document is delivered under when the body is XML rather
# than a form. Providers look for their own field names first and fall back to
# this one.
RESPONSE_XML_FIELD = "response_xml"


class ESignResponseXMLParser(BaseParser):
    """Wrap an ``application/xml`` body as ``{RESPONSE_XML_FIELD: <text>}``."""

    media_type = "application/xml"

    def parse(self, stream, media_type=None, parser_context=None):
        """Return the body as a single-entry mapping."""

        encoding = (parser_context or {}).get("encoding") or "utf-8"
        body = stream.read()
        if isinstance(body, bytes):
            body = body.decode(encoding, errors="replace")
        return {RESPONSE_XML_FIELD: body}


class ESignResponseTextXMLParser(ESignResponseXMLParser):
    """Same as :class:`ESignResponseXMLParser` for ``text/xml`` bodies."""

    media_type = "text/xml"
