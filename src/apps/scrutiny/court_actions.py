"""The court actions scrutiny and registration check (spec 0029 #3.3, #10.1).

Each is held at a court establishment. ``group`` is the PRD role the action
comes from, a display label for admin and seed authors: no code checks it.
"""

from apps.organizations.court_actions import define
from apps.organizations.enums import CourtLevel

EST = CourtLevel.ESTABLISHMENT

# Scrutiny officer (spec 0024 #4)
FLAG = define("scrutiny.flag", EST, "Mark fields and documents as errors", group="Scrutiny officer")
SEND_BACK = define(
    "scrutiny.send_back", EST, "Send a case back for correction", group="Scrutiny officer"
)
CHOOSE_COURTROOM = define(
    "scrutiny.choose_courtroom", EST, "Choose the courtroom of a case", group="Scrutiny officer"
)
FORWARD = define(
    "scrutiny.forward", EST, "Forward a case for registration", group="Scrutiny officer"
)

# Case registerer (spec 0024 #6)
REGISTER = define("registration.register", EST, "Register a case", group="Case registerer")
REGISTRATION_SEND_BACK = define(
    "registration.send_back",
    EST,
    "Send a forwarded case back for correction",
    group="Case registerer",
)

# The duty each stage belongs to. Start, which is not an action of its own,
# needs any one of them (spec 0029 #3.3), and so does seeing the stage's list.
SCRUTINY_STAGE = (FLAG, SEND_BACK, CHOOSE_COURTROOM, FORWARD)
REGISTRATION_STAGE = (REGISTER, REGISTRATION_SEND_BACK)
# Any of these at the latest round's establishment lets a person read the case
# in scrutiny (spec 0029 #10.1).
ALL = SCRUTINY_STAGE + REGISTRATION_STAGE
