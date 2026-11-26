"""The registry of court actions (spec 0029 #3).

An action is one thing a person does on the court side (forward a case, sign
an order), declared in code by the module that owns it, in
``<app>/court_actions.py``::

    from apps.organizations.court_actions import define
    from apps.organizations.enums import CourtLevel

    FORWARD = define("scrutiny.forward", CourtLevel.ESTABLISHMENT,
                     "Forward a case for registration", group="Scrutiny officer")

Code refers to an action by the returned constant, never by a string literal,
so a typo fails at import. ``OrganizationsConfig.ready()`` imports every
app's ``court_actions`` module, so the registry is complete before the first
request.

Codes are stored in the database as plain strings, so a code is never renamed
or reused (#3.4). ``group`` is the PRD role the action comes from, a display
label for admin and seed authors only: no code checks it.
"""

import re
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from .enums import CourtLevel

# ``<app>.<action>``, lowercase.
CODE_RE = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class CourtAction:
    """One declared court action."""

    code: str
    level: str
    label: str
    group: str
    scoped: bool = False

    @property
    def is_establishment(self) -> bool:
        """Whether the action is taken at an establishment rather than a courtroom."""
        return self.level == CourtLevel.ESTABLISHMENT

    def __str__(self) -> str:
        return self.code


_REGISTRY: dict[str, CourtAction] = {}
# Problems found while declaring, reported by system check E003 (#9.3) so a
# bad declaration names itself instead of only failing an import.
_PROBLEMS: list[str] = []


def define(code: str, level: str, label: str, *, group: str, scoped: bool = False) -> CourtAction:
    """Register and return a court action.

    Raises ``ImproperlyConfigured`` for a code declared twice, a malformed
    code or an unknown level.
    """
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        _PROBLEMS.append(f"Court action code {code!r} must be <app>.<action>, lowercase.")
        raise ImproperlyConfigured(_PROBLEMS[-1])
    if code in _REGISTRY:
        _PROBLEMS.append(f"Court action {code!r} is declared twice.")
        raise ImproperlyConfigured(_PROBLEMS[-1])
    if level not in CourtLevel.values:
        raise ImproperlyConfigured(f"Court action {code!r} has unknown level {level!r}.")
    action = CourtAction(code=code, level=str(level), label=label, group=group, scoped=scoped)
    _REGISTRY[code] = action
    return action


def get(code: str) -> CourtAction | None:
    """Return the registered action for ``code``, or ``None``."""
    return _REGISTRY.get(code)


def all() -> list[CourtAction]:  # noqa: A001 - the registry's public name (spec 0029 #1)
    """Return every registered action, by group then code."""
    return sorted(_REGISTRY.values(), key=lambda action: (action.group, action.code))


def is_registered(code: str) -> bool:
    """Whether ``code`` is a declared action."""
    return code in _REGISTRY


def resolve(action) -> CourtAction:
    """Return the registered ``CourtAction`` for a constant (or its code).

    Raises ``ImproperlyConfigured`` for an action no module declares, so a
    check against an undeclared action fails loudly rather than denying
    silently.
    """
    code = action.code if isinstance(action, CourtAction) else action
    registered = _REGISTRY.get(code)
    if registered is None:
        raise ImproperlyConfigured(f"Court action {code!r} is not declared by any module.")
    return registered


def problems() -> list[str]:
    """Declaration problems found so far (for system check E003)."""
    return list(_PROBLEMS)
