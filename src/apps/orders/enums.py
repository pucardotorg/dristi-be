"""Bounded values of the orders module (spec 0039)."""

from django.db import models


class OrderStatus(models.TextChoices):
    """Where an order is in its lifecycle (#4)."""

    DRAFT = "DRAFT", "Draft"
    SENT_FOR_SIGNING = "SENT_FOR_SIGNING", "Sent for signing"
    SIGNED = "SIGNED", "Signed"
    TRIGGERED = "TRIGGERED", "Triggered"
    DISCARDED = "DISCARDED", "Discarded"


# An order in one of these has been signed: its text, type, number and PDF are fixed (``PUB-06``).
SIGNED_STATUSES = (OrderStatus.SIGNED, OrderStatus.TRIGGERED)
# Statuses whose order data may still change while ``data_complete`` is false (#4, ``CMP-06``).
DATA_EDITABLE_STATUSES = (OrderStatus.DRAFT, OrderStatus.SENT_FOR_SIGNING, OrderStatus.SIGNED)


class NextHearingState(models.TextChoices):
    """What the order decides about the next hearing (``NXT-01``)."""

    UNSET = "UNSET", "Not set"
    LISTED = "LISTED", "Listed"
    NOT_LISTED_AGAIN = "NOT_LISTED_AGAIN", "Not listed again"


class EnteredFrom(models.TextChoices):
    """Where the next hearing was last written (``PLC-04``)."""

    ORDER = "ORDER", "Order"
    CAUSE_LIST = "CAUSE_LIST", "Cause list"


class ItemSource(models.TextChoices):
    """Who added an order item (#3.2)."""

    PERSON = "PERSON", "Person"
    PRESET = "PRESET", "Preset"
    BULK = "BULK", "Bulk action"
    SYSTEM = "SYSTEM", "System"
    READER = "READER", "Reading layer"


class ItemCategory(models.TextChoices):
    """Groups dropdown order items on the screen; contextual items have none (#3.3)."""

    FILINGS = "FILINGS", "Filings"
    DISPOSAL = "DISPOSAL", "Disposal"
    CASE_MANAGEMENT = "CASE_MANAGEMENT", "Case management"
    PROCESS = "PROCESS", "Process"
    MISCELLANEOUS = "MISCELLANEOUS", "Miscellaneous"


class Availability(models.TextChoices):
    """How an order item is reached (#3.3)."""

    DROPDOWN = "DROPDOWN", "Dropdown"
    CONTEXTUAL = "CONTEXTUAL", "Contextual"
    BOTH = "BOTH", "Dropdown or contextual"


class TriggerPhase(models.TextChoices):
    """The catalogue's *Workflow trigger order* (``PUB-03``)."""

    FIRST = "FIRST", "First"
    NORMAL = "NORMAL", "Normal"
    LAST = "LAST", "Last"


class RuleKind(models.TextChoices):
    """What a combination rule forbids (#3.4, ``ITM-07``)."""

    EXCLUSIVE = "EXCLUSIVE", "At most one item of the set per order"
    NO_REPEAT = "NO_REPEAT", "No item of the set twice"
    ONE_PER_TARGET = "ONE_PER_TARGET", "At most one item of the set per application"


class RunStep(models.TextChoices):
    """A step of an order's triggering (#9.2)."""

    HEARING = "HEARING", "Hearing"
    ITEM = "ITEM", "Order item"
    STAGE = "STAGE", "Case stage"


class RunStatus(models.TextChoices):
    """Where a workflow step is (#3.7)."""

    PENDING = "PENDING", "Pending"
    DONE = "DONE", "Done"
    FAILED = "FAILED", "Failed"
    BLOCKED = "BLOCKED", "Blocked"


class RoznamaStatus(models.TextChoices):
    """Where a Gujarat Roznama is (#3.10)."""

    AWAITING_SIGNATURE = "AWAITING_SIGNATURE", "Awaiting signature"
    SIGNED = "SIGNED", "Signed"


class NumberSeries(models.TextChoices):
    """The number series an order is numbered from (#3.8)."""

    ORDER = "ORDER", "Order"
    ROZNAMA = "ROZNAMA", "Roznama"


class SigningMethod(models.TextChoices):
    """How an order is signed (``SGN-05``)."""

    AADHAAR_ESIGN = "AADHAAR_ESIGN", "Aadhaar e-sign"
    DSC = "DSC", "Digital signature certificate"


class OrderRole(models.TextChoices):
    """The court roles order actions need, held per courtroom (#2.1, ``court-roles.md``)."""

    ORDER_DRAFTER = "ORDER_DRAFTER", "Order drafter"
    ORDER_DATA_FILLER = "ORDER_DATA_FILLER", "Order data filler"
    NEXT_HEARING_SETTER = "NEXT_HEARING_SETTER", "Next hearing setter"
    ORDER_SIGNER = "ORDER_SIGNER", "Order signer"


class Stage(models.TextChoices):
    """The Pending orders tabs, read from the order's facts and never stored (#4, ``PND-02``)."""

    DRAFTING = "DRAFTING", "Drafting"
    AWAITING_SIGNATURE = "AWAITING_SIGNATURE", "Awaiting signature"
    ORDER_DATA_TO_FILL = "ORDER_DATA_TO_FILL", "Order data to fill"
    TRIGGERED = "TRIGGERED", "Triggered"


class TaskKey(models.TextChoices):
    """The order pending tasks (#12.1)."""

    DRAFT_ORDER = "draft_order", "Draft order"
    SIGN_ORDER = "sign_order", "Sign order"
    FILL_ORDER_DATA = "fill_order_data", "Fill order data"
    SIGN_ROZNAMA = "sign_roznama", "Sign Roznama"


class FieldInput(models.TextChoices):
    """The kinds of input an order item field takes (#6.3)."""

    TEXT = "TEXT", "Text"
    DATE = "DATE", "Date"
    AMOUNT = "AMOUNT", "Amount"
    ENUM = "ENUM", "One of a fixed list"
    MASTER = "MASTER", "A master-data code"
    PARTY = "PARTY", "A person in the case"
    PARTIES = "PARTIES", "People in the case"
    HEARING_PURPOSE = "HEARING_PURPOSE", "A hearing purpose"
    RECORD = "RECORD", "Read only, from the record"
    PROCESS_RECIPIENTS = "PROCESS_RECIPIENTS", "Process recipients"


SHORTCUT_SCOPE_ORDER_TEXT = "ORDER_TEXT"
