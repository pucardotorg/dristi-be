"""What orders need from modules that are not built yet (spec 0039 #1.1, #2.1, #12.1).

Spec 0039 relies on court roles per courtroom (``court-roles.md``), the 0011
workflow engine with its pending tasks and case-stage events, and a case
outcome that ``apps.cases`` does not record. Every call orders makes to them
goes through this module, so each stand-in below is replaced here, and only
here, when the real one lands (the same arrangement as
``apps/hearings/ports.py`` and ``apps/scrutiny/ports.py``):

* Roles — Django groups named after the role, counted only at the deployment's
  one establishment (``SCRUTINY_ESTABLISHMENT_ID``) and its courtrooms.
* Tasks — none yet: the three order tasks are logged, not stored. Pending orders
  never read tasks: its tabs come from the order's own facts (#4, ``PND-02``).
* Stage events — logged and sent as ``case_stage_event``; nothing moves a case
  stage until 0011 exists (``PUB-05``).
* Outcome — logged; ``Case`` has no outcome field yet.
"""

import logging

from django.dispatch import Signal

from apps.hearings import ports as hearing_ports
from apps.hearings.enums import HearingRole  # noqa: F401
from apps.organizations.models import Organization

from .enums import OrderRole

logger = logging.getLogger(__name__)

# Sent for each stage event, until 0011's ``CaseWorkflowService.dispatch`` exists.
case_stage_event = Signal()


def court_roles(user, court_id):
    """Return the order roles ``user`` holds in the courtroom; none in any other court.

    PLACEHOLDER: the user's groups named after ``OrderRole``, at the configured
    establishment's courtrooms only (``RLE-02b``).
    """
    if not user or not user.is_authenticated or court_id is None:
        return frozenset()
    establishment = hearing_ports.configured_establishment()
    if establishment is None:
        return frozenset()
    in_establishment = (
        str(court_id) == str(establishment)
        or Organization.objects.filter(pk=court_id, parent_id=establishment).exists()
    )
    if not in_establishment:
        return frozenset()
    names = user.groups.filter(name__in=OrderRole.values).values_list("name", flat=True)
    return frozenset(OrderRole(name) for name in names)


def is_court_staff(user, court_id):
    """Whether ``user`` holds any court role (hearing or order) in the courtroom (``RLE-06``)."""
    if court_roles(user, court_id):
        return True
    return bool(hearing_ports.court_roles(user, court_id))


def holds_role_anywhere(user, role=None):
    """Whether ``user`` holds ``role`` (any court role when ``None``) in some courtroom.

    For endpoints that belong to a person and not to one courtroom: the catalogue and
    a person's own shortcuts (``SHC-06``). PLACEHOLDER: groups, at the one establishment.
    """
    if not user or not user.is_authenticated or hearing_ports.configured_establishment() is None:
        return False
    names = [role] if role else [*OrderRole.values, *HearingRole.values]
    return user.groups.filter(name__in=names).exists()


# Pending tasks (#12.1)


def open_task(order_id, task_key, *, title, role=None, court_id=None):
    """Open a pending task for ``order_id``. PLACEHOLDER: logged only."""
    logger.info("event=ORDER_TASK_OPENED order=%s task=%s title=%s", order_id, task_key, title)


def complete_task(order_id, task_key):
    """Complete the order's open task ``task_key``. PLACEHOLDER: logged only."""
    logger.info("event=ORDER_TASK_COMPLETED order=%s task=%s", order_id, task_key)


def expire_task(order_id, task_key):
    """Expire the order's open task ``task_key``. PLACEHOLDER: logged only."""
    logger.info("event=ORDER_TASK_EXPIRED order=%s task=%s", order_id, task_key)


def open_item_task(order_id, item_id, task_key, *, side, due=None, detail=None):
    """Open a citizen-side task for an order item (#9.3). PLACEHOLDER: logged only.

    Returns the task reference the handler records in its run result.
    """
    reference = f"ORDER_ITEM:{item_id}:{task_key}"
    logger.info(
        "event=ORDER_ITEM_TASK_OPENED order=%s item=%s task=%s side=%s due=%s",
        order_id,
        item_id,
        task_key,
        side,
        due,
    )
    return reference


def complete_item_task(item_id, task_key):
    """Complete an item's citizen-side task. PLACEHOLDER: logged only."""
    logger.info("event=ORDER_ITEM_TASK_COMPLETED item=%s task=%s", item_id, task_key)


def complete_case_task(case_id, task_key):
    """Complete the case's open task ``task_key``, e.g. ``take_cognizance``. PLACEHOLDER."""
    logger.info("event=CASE_TASK_COMPLETED case=%s task=%s", case_id, task_key)


# Case stage and outcome (#9.4)


def dispatch_stage_event(case_id, event, context):
    """Dispatch a case-stage event; the 0011 definition decides what it means. PLACEHOLDER."""
    logger.info("event=CASE_STAGE_EVENT case=%s stage_event=%s context=%s", case_id, event, context)
    case_stage_event.send(sender=None, case_id=case_id, event=event, context=context)


def record_outcome(case_id, outcome, order_id):
    """Record the case outcome a case-closing item states. PLACEHOLDER: logged only."""
    logger.info("event=CASE_OUTCOME case=%s outcome=%s order=%s", case_id, outcome, order_id)


def current_stage(case_id):
    """Return the case's workflow stage as ``{"key", "label"}``, or ``None`` (#6.1).

    PLACEHOLDER: stages are not modelled until 0011.
    """
    return None
