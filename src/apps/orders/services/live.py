"""The live view of a draft: a change feed everyone with the order open polls (#5.4, ``DFT-02``).

``GET /orders/{id}/changes/?since=<text_version>.<data_version>`` returns ``304`` when
nothing changed. Push is out of scope in this version (design decision 21).
"""

from .. import conf


def etag(order):
    """The ETag of the order's two versions."""
    return f'"{order.text_version}.{order.data_version}"'


def parse_since(value):
    """Return ``(text_version, data_version)`` from ``"14.6"``, or ``None`` when malformed."""
    try:
        text, data = str(value).strip('"').split(".")
        return int(text), int(data)
    except (ValueError, AttributeError):
        return None


def unchanged(order, since):
    """Whether the client already has this order's current versions."""
    return parse_since(since) == (order.text_version, order.data_version)


def poll_seconds():
    return conf.live_poll_seconds()
