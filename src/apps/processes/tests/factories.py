"""Builders shared by the processes tests.

Users, courts and cases come from the hearings test factories. Processes are
started the way the product starts them, through
``issue.start_from_order_item``; only steps not built yet (signing) are
stood in for by ``mark_signed``.
"""

import uuid
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command

from apps.cases.models import CaseContact, CaseParticipant, ContactType, ParticipantRole
from apps.core.models import Configuration
from apps.hearings.tests.factories import make_user
from apps.payments.enums import ChargeType, ReferenceType
from apps.payments.models import DemandItem
from apps.payments.services import DemandService, PaymentService
from apps.payments.tasks import notify_payment_completed
from apps.processes import court_actions
from apps.processes.enums import ProcessStatus
from apps.processes.models import Process
from apps.processes.services import issue

SEED = Path(__file__).resolve().parents[4] / "data" / "seed" / "core" / "processes"
MOBILE = "+919812345678"


def seed_masters():
    """Load the process masters and Kerala's court fees, as a deployment does."""
    call_command("seed", str(SEED), verbosity=0)
    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "KL"}
    )
    for code in ("notice", "summons", "warrant"):
        Configuration.objects.update_or_create(
            config_set="processes.kl",
            config_key=f"court_fee.{code}",
            defaults={"config_value": "2.00"},
        )


def make_staff(*actions, name="Staff"):
    """Court staff allowed ``actions`` (all process actions by default)."""
    return make_user(*(actions or court_actions.ALL), name=name)


def party(case, role):
    return CaseParticipant.objects.get(case=case, role=role)


def add_mobile(participant, number=MOBILE):
    CaseContact.objects.create(
        case=participant.case,
        case_participant=participant,
        contact_type=ContactType.MOBILE_NUMBER,
        value=number,
        ordinal=1,
    )


def address_ids(participant):
    return list(
        CaseContact.objects.filter(
            case_participant=participant, contact_type=ContactType.ADDRESS
        ).values_list("address_id", flat=True)
    )


def accused(case):
    return party(case, ParticipantRole.ACCUSED)


def recipient(participant, *channels, **values):
    """One recipient's values: the given channels, at every address on the record."""
    return {
        "recipient_id": str(participant.pk),
        "channels": list(channels),
        "addresses": [str(each) for each in address_ids(participant)],
        **values,
    }


def start(case, *recipients, item_code="ISSUE_OF_SUMMONS", order_id=None, order_item_id=None, **kw):
    """Trigger a Process-category order item; return its processes in creation order."""
    ids = issue.start_from_order_item(
        case_id=case.pk,
        order_id=order_id or uuid.uuid4(),
        order_item_id=order_item_id or uuid.uuid4(),
        item_code=item_code,
        values={"recipients": list(recipients)},
        **kw,
    )
    return list(Process.objects.filter(pk__in=ids).order_by("created_at"))


def mark_signed(process, status=ProcessStatus.SIGNED, **fields):
    """Stand in for signing, which is not built yet: the process as signing leaves it."""
    Process.objects.filter(pk=process.pk).update(
        status=status, signed_file_id="signed-file", expiry_fixed=True, **fields
    )
    process.refresh_from_db()
    return process


def pay(demand, item_ids, user):
    """Pay ``item_ids`` of ``demand`` through payments, and deliver its completion notice."""
    payment = PaymentService.create_payment(
        demand=demand,
        demand_item_ids=list(item_ids),
        client_request_id=f"pay-{uuid.uuid4()}",
        actor=user,
    ).payment
    PaymentService.confirm_payment(payment)
    notify_payment_completed.fn(str(payment.pk))


def pay_fees(processes, user):
    """Pay the processes' court-fee items."""
    items = [process.demand_item_id for process in processes]
    pay(DemandItem.objects.get(pk=items[0]).demand, items, user)


def prepay(case, amount, user):
    """Pay process court fee up front, as e-filing does, into the case's pool (``FEE-04``)."""
    demand = DemandService.raise_demand(
        case=case.pk,
        reference_type=ReferenceType.OTHER,
        reference_id="filing",
        items=[
            {
                "charge_type": ChargeType.PROCESS_COURT_FEE,
                "description": "Upfront process court fee",
                "unit_amount": Decimal(amount),
            }
        ],
    )
    pay(demand, [demand.items.get().pk], user)
