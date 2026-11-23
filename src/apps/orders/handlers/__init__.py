"""Order item handlers (spec 0039 #1.2, #9.3)."""

from . import base
from .base import (
    DuplicateHandler,
    ItemContext,
    OrderItemHandler,
    Problem,
    RunResult,
    get,
    register,
    registered,
)

__all__ = [
    "DuplicateHandler",
    "ItemContext",
    "OrderItemHandler",
    "Problem",
    "RunResult",
    "base",
    "get",
    "register",
    "register_builtin",
    "registered",
]


def register_builtin():
    """Register the handlers owned here, then the stand-ins for modules not built yet.

    Idempotent: ``AppConfig.ready()`` may run more than once in tests. A real
    handler registered earlier by another module is never replaced by a stand-in.
    """
    from .builtin import BUILTIN
    from .placeholders import PLACEHOLDERS

    for handler_class in BUILTIN:
        if all(code not in base.registered() for code in handler_class.item_codes):
            register(handler_class())
    for handler_class in PLACEHOLDERS:
        handler = handler_class()
        pending = tuple(code for code in handler.item_codes if code not in base.registered())
        if pending:
            handler.item_codes = pending
            register(handler)
