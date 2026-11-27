"""Who a process can be addressed to, and what the order screen fills in for them (#5.4).

Shared by the fan-out (``services.issue``), which checks an order item's
recipients, and the order screen's recipient list, which offers them with
their destinations and defaults. Each rule is written once here.
"""

from dataclasses import dataclass

from apps.address.models import Address
from apps.cases.models import ParticipantRole
from apps.cases.selectors import ProcessRecipient, process_recipients

from .enums import RecipientType, Side
from .models import Process

# Who is directed to take steps when the order does not say (``AUT-02``).
OPPOSITE_SIDE = {
    ParticipantRole.ACCUSED: Side.COMPLAINANT,
    ParticipantRole.COMPLAINANT: Side.ACCUSED,
}


def recipient_type(recipient: ProcessRecipient) -> str:
    if recipient.role == ParticipantRole.WITNESS:
        return RecipientType.WITNESS
    if recipient.role == ParticipantRole.COMPLAINANT:
        return RecipientType.COMPLAINANT
    if recipient.is_person_in_charge:
        return RecipientType.ACCUSED_PERSON_IN_CHARGE
    return RecipientType.ACCUSED


def default_party_taking_steps(recipient: ProcessRecipient) -> str | None:
    """The other side for a party, the calling side for a witness; else None (``AUT-02``, ``AUT-03``)."""
    return OPPOSITE_SIDE.get(recipient.role) or recipient.witness_side


def preselected_ids(recipients) -> set:
    """The recipient the order screen pre-selects, if any (``AUT-05``).

    Until an accused has joined, the accused where there is exactly one.
    Once one has joined, ``AUT-06`` pre-selects the one witness not yet
    examined; examination is not recorded yet, so nothing is pre-selected.
    """
    accused = [each for each in recipients if each.role == ParticipantRole.ACCUSED]
    if len(accused) == 1 and not any(each.has_joined for each in accused):
        return {accused[0].id}
    return set()


@dataclass(frozen=True)
class OrderRecipient:
    """One recipient as the order screen offers it, with their destinations and defaults."""

    id: object
    type: str
    name: str
    party_taking_steps: str | None
    preselected: bool
    mobiles: tuple
    emails: tuple
    addresses: list
    police_station: object = None


def last_police_stations(case_id) -> dict:
    """Each recipient's police station in their latest process on a police channel (``AUT-04``).

    A police process names a station, not an address, so the station is
    held per recipient. One from e-filing is free text, not yet matched to
    the master (spec 0028 open question 2), so it is not offered.
    """
    held = {}
    rows = (
        Process.objects.filter(case_id=case_id, police_station__isnull=False)
        .select_related("police_station")
        .order_by("recipient_id", "-created_at")
    )
    for process in rows:
        held.setdefault(process.recipient_id, process.police_station)
    return held


def for_order_screen(case_id) -> list[OrderRecipient]:
    """The case's recipients for a Process-category item, with what the screen fills in (#5.4).

    Every address on the record is offered, and pre-selected by the screen
    (``AUT-07``); the channels pre-selected per type come from the process
    types (``AUT-08``); the police station is the one used in an earlier
    round, if any (``AUT-04``).
    """
    recipients = list(process_recipients(case_id).values())
    preselected = preselected_ids(recipients)
    stations = last_police_stations(case_id)
    addresses = Address.objects.in_bulk(
        [address_id for each in recipients for address_id in each.address_ids]
    )
    return [
        OrderRecipient(
            id=each.id,
            type=recipient_type(each),
            name=each.name,
            party_taking_steps=default_party_taking_steps(each),
            preselected=each.id in preselected,
            mobiles=each.mobiles,
            emails=each.emails,
            addresses=[addresses[address_id] for address_id in each.address_ids],
            police_station=stations.get(each.id),
        )
        for each in recipients
    ]
