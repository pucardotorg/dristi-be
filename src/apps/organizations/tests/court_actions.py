"""Court actions declared for the organizations tests only (spec 0029 #3.1).

No court module declares actions yet, so the tests declare their own under the
``testing`` app prefix. Importing this module registers them once per test run.
"""

from apps.organizations import court_actions
from apps.organizations.court_actions import define
from apps.organizations.enums import CourtLevel

EST = CourtLevel.ESTABLISHMENT
ROOM = CourtLevel.COURTROOM


def _define(code, level, label, *, group, scoped=False):
    """Declare once, so a re-import (or another test module) reuses the same action."""
    return court_actions.get(code) or define(code, level, label, group=group, scoped=scoped)


FLAG = _define("testing.flag", EST, "Flag errors", group="Scrutiny officer")
SEND_BACK = _define("testing.send_back", EST, "Send back", group="Scrutiny officer")
FORWARD = _define("testing.forward", EST, "Forward", group="Scrutiny officer")
REGISTER = _define("testing.register", EST, "Register", group="Case registerer")
SIGN = _define("testing.sign", ROOM, "Sign orders", group="Order signer")
EDIT = _define("testing.edit", ROOM, "Edit orders", group="Order drafter")
PROCESS_SIGN = _define(
    "testing.process_sign", ROOM, "Sign processes", group="Process signer", scoped=True
)
PROCESS_SEND = _define(
    "testing.process_send", ROOM, "Send processes", group="Process dispatcher", scoped=True
)

SCRUTINY_STAGE = (FLAG, SEND_BACK, FORWARD)
