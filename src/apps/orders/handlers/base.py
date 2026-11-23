"""The order item handler contract and its registry (spec 0039 #1.2).

A module whose thing an order item acts on registers an ``OrderItemHandler``
from its ``AppConfig.ready()``. Orders calls the handler and never imports the
module. A handler receives ids and values only, never an ``Order``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal
from uuid import UUID


@dataclass(frozen=True)
class ItemContext:
    """What a handler may know about the order item it is asked about.

    ``item_id`` is empty while an item is being added; ``source`` is the
    ``ItemSource`` of the person or process adding it, empty when reading an
    item that already exists.
    """

    case_id: UUID
    order_id: UUID
    hearing_id: UUID | None = None
    target_type: str = ""
    target_id: UUID | None = None
    item_id: UUID | None = None
    source: str = ""


@dataclass(frozen=True)
class Problem:
    """Something wrong with an item: ``field`` is ``values.<key>`` or ``target_id``."""

    field: str
    code: str
    message: str


@dataclass(frozen=True)
class RunResult:
    """What one execution of an item's workflow did (``payload``: ids it created)."""

    status: Literal["DONE", "FAILED"]
    payload: dict = field(default_factory=dict)
    error_code: str = ""


class OrderItemHandler(ABC):
    """What an order item does, and what it needs, beyond its catalogue row."""

    item_codes: ClassVar[tuple[str, ...]]
    # A stand-in for a module that is not built yet; the real handler replaces it.
    placeholder: ClassVar[bool] = False

    def unavailable_reason(self, ctx: ItemContext) -> tuple[str, str] | None:
        """Return ``(code, message)`` if the item cannot be added to this order now (``ITM-03``)."""
        return None

    def validate_target(self, ctx: ItemContext) -> list[Problem]:
        """Check the application a contextual item names (``ITM-04``)."""
        return []

    def defaults(self, ctx: ItemContext) -> dict:
        """Return preselected values, only where nothing has to be guessed (``VAR-02``, ``VAR-03``)."""
        return {}

    def validate(self, ctx: ItemContext, values: dict, *, complete: bool) -> list[Problem]:
        """Check the values: shape on every save, completeness at *Mark complete* (``CMP-02``)."""
        return []

    def summary(self, ctx: ItemContext, values: dict) -> str:
        """The item's line in lists."""
        return ""

    @abstractmethod
    def execute(self, ctx: ItemContext, values: dict, *, run_id: UUID) -> RunResult:
        """Run the item's workflow once the order is triggered.

        Called in a Dramatiq actor and idempotent on ``run_id``: a redelivered run
        returns the first result and creates nothing twice.
        """


class DuplicateHandler(Exception):  # noqa: N818
    """A second handler was registered for an item code."""


_registry: dict[str, OrderItemHandler] = {}


def register(handler):
    """Register ``handler`` for each of its item codes.

    A second handler for a code is refused, unless the one there is a
    ``placeholder``: the owning module's real handler replaces it.
    """
    for code in handler.item_codes:
        current = _registry.get(code)
        if current is not None and not current.placeholder:
            raise DuplicateHandler(f"{code} already has a handler ({type(current).__name__}).")
    for code in handler.item_codes:
        _registry[code] = handler


def unregister(code):
    """Remove the handler of ``code`` (tests)."""
    _registry.pop(code, None)


def get(code):
    """Return the handler registered for ``code``, or ``None``."""
    return _registry.get(code)


def registered():
    """Return ``{code: handler}`` for every registered handler."""
    return dict(_registry)
