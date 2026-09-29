"""Condition evaluation for lazy approval-step routing.

``ApprovalStep.condition`` holds a small declarative rule that is evaluated
against the request being routed. An empty condition always matches.

Supported shapes::

    {}                                      # always matches
    {"field": "data.amount", "op": "gt", "value": 1000}
    {"all": [<condition>, ...]}
    {"any": [<condition>, ...]}
    {"not": <condition>}

Supported operators: ``eq``, ``ne``, ``gt``, ``gte``, ``lt``, ``lte``,
``in``, ``not_in``, ``contains``, ``exists``.

Fields are dotted paths resolved against the routing context:

- ``data.<key>`` — the request's ``data`` JSON (nested paths supported)
- ``request_type.code`` / ``request_type.name``
- ``requester.mobile_number`` / ``requester.name`` / ``requester.email`` /
  ``requester.role`` / ``requester.id`` / ``requester.groups`` (list of group
  names) / ``requester.is_staff``
- ``version``, ``current_step``, ``status``
"""

from typing import Any

MISSING = object()


class ConditionError(Exception):
    """Raised when a condition is malformed."""


def build_context(request) -> dict:
    """Return the evaluation context for a request."""
    requester = request.requester
    return {
        "data": request.data or {},
        "request_type": {
            "code": request.request_type.code,
            "name": request.request_type.name,
        },
        "requester": {
            "id": str(requester.pk) if requester else None,
            "mobile_number": getattr(requester, "mobile_number", None),
            "name": getattr(requester, "name", None),
            "email": getattr(requester, "email", None),
            "role": getattr(requester, "role", None),
            "is_staff": getattr(requester, "is_staff", False),
            "groups": (list(requester.groups.values_list("name", flat=True)) if requester else []),
        },
        "version": request.version,
        "current_step": request.current_step,
        "status": request.status,
    }


def resolve_field(context: dict, path: str) -> Any:
    """Resolve a dotted path against the context, returning ``MISSING`` if absent."""
    current: Any = context
    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return MISSING
    return current


def evaluate_condition(condition: dict | None, context: dict) -> bool:
    """Return ``True`` when ``condition`` matches ``context``."""
    if not condition:
        return True
    if not isinstance(condition, dict):
        raise ConditionError("Condition must be a JSON object.")

    if "all" in condition:
        return all(evaluate_condition(child, context) for child in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(child, context) for child in condition["any"])
    if "not" in condition:
        return not evaluate_condition(condition["not"], context)

    if "field" not in condition:
        raise ConditionError("Condition must contain 'field', 'all', 'any' or 'not'.")

    actual = resolve_field(context, condition["field"])
    operator = condition.get("op", "eq")
    expected = condition.get("value")
    return _apply_operator(operator, actual, expected)


def _apply_operator(operator: str, actual: Any, expected: Any) -> bool:
    """Apply a single comparison operator, tolerating missing values."""
    if operator == "exists":
        return (actual is not MISSING) is bool(expected if expected is not None else True)

    if actual is MISSING:
        return operator in ("ne", "not_in")

    try:
        if operator == "eq":
            return actual == expected
        if operator == "ne":
            return actual != expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "in":
            return actual in (expected or [])
        if operator == "not_in":
            return actual not in (expected or [])
        if operator == "contains":
            return expected in (actual or [])
    except TypeError:
        return False

    raise ConditionError(f"Unsupported condition operator: {operator!r}.")
