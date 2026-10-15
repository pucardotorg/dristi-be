"""Shared fixtures for the PDF test suite."""

from __future__ import annotations

import io
from random import randint
from uuid import uuid4

from PIL import Image

from apps.pdf.models import PDFTemplate, PDFTemplateVersion
from apps.users.models import RegistrationStatus, User

FORMAT_CONFIG = {
    "page": {"size": "A4"},
    "metadata": {"title": "{{ title }} {{ case_number }}"},
    "header": {"left": "{{ title }}", "right": "Page {page} of {pages}", "line": True},
    "footer": {"center": "Tenant {{ meta.tenant_id }}"},
    "body": [
        {"type": "heading", "text": "{{ title }}", "align": "center"},
        {"type": "paragraph", "text": "Case <b>{{ case_number }}</b> to {{ data.name }}."},
        {
            "type": "table",
            "source": "witnesses",
            "as": "w",
            "columns": [
                {"header": "#", "value": "{{ loop.index }}", "width": 30},
                {"header": "Name", "value": "{{ w.name }}"},
            ],
            "when": "witnesses",
        },
    ],
}

DATA_CONFIG = {
    "mappings": [
        {"type": "direct", "target": "case_number", "path": "$.case.number"},
        {
            "type": "direct",
            "target": "witnesses",
            "path": "$.witnesses[*]",
            "columns": {"name": "$.name"},
        },
        {"type": "localization", "target": "title", "code": "SUMMONS"},
    ],
    "localization": {"messages": {"en_IN": {"SUMMONS": "Summons"}}},
    "significant_fields": ["$.case.number", "$.name"],
}

REQUEST_DATA = {
    "case": {"number": "CC/12/2026"},
    "name": "Asha",
    "witnesses": [{"name": "W1"}, {"name": "W2"}],
    "requested_at": "2026-10-01T10:00:00Z",
}

BULK_FORMAT_CONFIG = {
    "body": [
        {"type": "heading", "text": "Notice {{ data.number }}"},
        {"type": "paragraph", "text": "To {{ data.name }} ({{ request.court }})"},
    ]
}

BULK_DATA_CONFIG = {
    "bulk": {"records_path": "$.records", "merge": True, "max_records_per_document": 2},
}


def make_user(**overrides):
    """Create a fully registered user."""
    handle = f"pdf-{uuid4().hex[:8]}"
    defaults = {
        "mobile_number": f"+919{randint(0, 999_999_999):09d}",
        "name": handle,
        "email": f"{handle}@example.com",
        "password": "test-password",
        "registration_status": RegistrationStatus.COMPLETE,
    }
    defaults.update(overrides)
    return User.objects.create_user(**defaults)


def make_template(
    key="case-summons", format_config=None, data_config=None, *, is_active=True, **template_kwargs
):
    """Create a template with one active version and return the version."""
    template, _ = PDFTemplate.objects.get_or_create(
        key=key,
        defaults={"name": key.replace("-", " ").title(), "is_active": is_active, **template_kwargs},
    )
    return PDFTemplateVersion.objects.create(
        template=template,
        format_config=format_config if format_config is not None else FORMAT_CONFIG,
        data_config=data_config if data_config is not None else DATA_CONFIG,
    )


def make_bulk_template(key="bulk-notice", **data_overrides):
    """Create a bulk template (2 records per chunk, merge on)."""
    data_config = {
        **BULK_DATA_CONFIG,
        "bulk": {**BULK_DATA_CONFIG["bulk"], **data_overrides},
    }
    return make_template(key, BULK_FORMAT_CONFIG, data_config)


def bulk_request(count: int) -> dict:
    """Return a bulk payload with ``count`` records."""
    return {
        "court": "District Court",
        "records": [{"number": index + 1, "name": f"Person {index + 1}"} for index in range(count)],
    }


def png_bytes(width=20, height=10, color=(255, 0, 0)) -> bytes:
    """Return a small PNG image."""
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def simple_pdf(pages: int = 1, text: str = "Hello") -> bytes:
    """Return a minimal reportlab-generated PDF."""
    from reportlab.pdfgen.canvas import Canvas

    out = io.BytesIO()
    canvas = Canvas(out, invariant=1)
    for page in range(pages):
        canvas.drawString(72, 720, f"{text} {page + 1}")
        canvas.showPage()
    canvas.save()
    return out.getvalue()
