"""Expand a ``format_config`` with a render context into a resolved document.

This is the "render template fragments" step of spec 0016 #5. It evaluates
``when`` conditions, repeats tables, lists and groups over ``source`` lists,
renders every text placeholder with Jinja, and resolves image/QR references
to ``ImageData``. The result contains no templates or expressions, so the
renderer stays a pure layout engine.

Block reference (``format_config.body``)::

    {"type": "heading", "text": "{{ title }}", "level": 1, "align": "center"}
    {"type": "paragraph", "text": "To <b>{{ data.name }}</b>,", "style": "default"}
    {"type": "table", "source": "witnesses", "as": "w",
     "columns": [{"header": "#", "value": "{{ loop.index }}", "width": 30},
                 {"header": "Name", "value": "{{ w.name }}", "width": "60%"}]}
    {"type": "list", "source": "accused", "as": "a", "item": "{{ a.name }}", "ordered": true}
    {"type": "image", "source": "court_seal", "width": 80}
    {"type": "qr", "value": "https://x/{{ data.id }}", "size": 90}
    {"type": "group", "source": "records", "as": "record", "blocks": [...]}
    {"type": "spacer", "height": 12} / {"type": "line"} / {"type": "page_break"}

Any block may carry ``"when": "<expression>"`` and is skipped when it is falsy.
Inside repeated content ``loop.index`` (1-based), ``loop.first`` and
``loop.last`` are available.
"""

from __future__ import annotations

from ..exceptions import PDFRequestDataError
from ..renderer import ImageData
from .mapping.qr import make_qr
from .templating import evaluate, render_text


def compose(format_config: dict, variables: dict) -> dict:
    """Return the resolved document for one render context."""
    return {
        "page": format_config.get("page") or {},
        "metadata": {
            field: render_text(text, variables, escape_output=False)
            for field, text in (format_config.get("metadata") or {}).items()
        },
        "styles": format_config.get("styles") or {},
        "header": _band(format_config.get("header"), variables),
        "footer": _band(format_config.get("footer"), variables),
        "sections": [blocks(format_config.get("body") or [], variables)],
    }


def compose_many(format_config: dict, contexts: list[dict]) -> dict:
    """Return one document holding a section (starting on a new page) per context.

    Used for bulk chunks: every record of the chunk becomes its own section of
    the chunk's document. Header/footer/metadata come from the first context.
    """
    if not contexts:
        raise PDFRequestDataError("A bulk chunk has no records.")
    document = compose(format_config, contexts[0])
    document["sections"] = [blocks(format_config.get("body") or [], ctx) for ctx in contexts]
    return document


def _band(band: dict | None, variables: dict) -> dict | None:
    if not band:
        return None
    resolved = dict(band)
    for position in ("left", "center", "right"):
        if band.get(position):
            # {page}/{pages} are single-brace tokens the renderer fills in, so
            # they pass through Jinja untouched.
            resolved[position] = render_text(band[position], variables)
    return resolved


def _iterate(block: dict, variables: dict):
    """Yield the scoped variables for each repetition of ``block``."""
    items = evaluate(block["source"], variables)
    if items is None:
        items = []
    if not isinstance(items, list | tuple):
        raise PDFRequestDataError(f"{block['source']!r} is not a list.")
    name = block.get("as", "item")
    total = len(items)
    for index, item in enumerate(items):
        yield {
            **variables,
            name: item,
            "loop": {
                "index": index + 1,
                "index0": index,
                "first": index == 0,
                "last": index == total - 1,
            },
        }


def blocks(config_blocks: list, variables: dict) -> list:
    """Resolve a list of configured blocks."""
    resolved = []
    for block in config_blocks:
        if "when" in block and not evaluate(block["when"], variables):
            continue
        resolved.extend(_block(block, variables))
    return resolved


def _block(block: dict, variables: dict) -> list:
    kind = block["type"]
    base = {key: value for key, value in block.items() if key not in ("when", "source", "as")}

    if kind in ("paragraph", "text", "heading"):
        return [{**base, "text": render_text(block["text"], variables)}]

    if kind == "table":
        columns = [
            {
                **column,
                "header": render_text(column.get("header", ""), variables),
            }
            for column in block["columns"]
        ]
        rows = [[render_text(cell, variables) for cell in row] for row in block.get("rows", [])]
        if "source" in block:
            for scoped in _iterate(block, variables):
                rows.append(
                    [render_text(column.get("value", ""), scoped) for column in block["columns"]]
                )
        return [{**base, "columns": columns, "rows": rows}]

    if kind == "list":
        items = [render_text(item, variables) for item in block.get("items", [])]
        if "source" in block:
            template = block.get("item", "{{ " + block.get("as", "item") + " }}")
            items.extend(render_text(template, scoped) for scoped in _iterate(block, variables))
        base.pop("item", None)
        return [{**base, "items": items}]

    if kind == "image":
        image = evaluate(block["source"], variables)
        if image is not None and not isinstance(image, ImageData):
            raise PDFRequestDataError(f"{block['source']!r} does not resolve to an image.")
        return [{**base, "image": image}]

    if kind == "qr":
        if "value" in block:
            value = render_text(block["value"], variables, escape_output=False)
            image = make_qr(value, error_correction=block.get("error_correction", "M"))
        else:
            image = evaluate(block["source"], variables)
            if image is not None and not isinstance(image, ImageData):
                raise PDFRequestDataError(f"{block['source']!r} does not resolve to a QR image.")
        base.pop("value", None)
        return [{**base, "image": image}]

    if kind == "group":
        if "source" not in block:
            return blocks(block["blocks"], variables)
        out = []
        for scoped in _iterate(block, variables):
            out.extend(blocks(block["blocks"], scoped))
        return out

    return [base]
