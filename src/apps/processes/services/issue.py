"""Starting processes from a triggered order item (spec 0028 #5).

``start_from_order_item`` is the entry point the orders module calls when a
Process-category item is triggered, after the hearing step. The orders
module does not exist yet; when it does, it reaches this through the
``OrderItemHandler`` this app registers, and this function stays the same.

The item's ``values`` are checked first, and nothing is written unless all of
them hold; every refusal names its field under ``values``. Then, in one
transaction under the case's lock: the destinations added on the order
screen are saved to the recipient's record (``PRC-05``), one process is
created per recipient, channel and destination (``PRC-02``), and the fee is
drawn from the pool, with a demand for the balance (#6).
"""

from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.api.errors import BusinessError
from apps.cases.models import CaseParticipant, ContactType
from apps.cases.selectors import get_case_summaries, process_recipients
from apps.cases.services.contacts import add_contact
from apps.hearings.selectors import get_hearing, next_hearing
from apps.locations.models import Location

from .. import errors
from ..enums import DestinationKind, Side
from ..models import (
    DESTINATION_FIELDS,
    Process,
    ProcessCaseLock,
    ProcessRound,
    ProcessType,
    ProcessTypeChannel,
)
from ..recipients import default_party_taking_steps, recipient_type
from . import fees, steps, transitions
from .expiry import expires_at

# The contact a destination added on the order screen is saved as.
ADDED_CONTACT_TYPES = {
    DestinationKind.MOBILE: ContactType.MOBILE_NUMBER,
    DestinationKind.EMAIL: ContactType.EMAIL,
    DestinationKind.POSTAL: ContactType.ADDRESS,
}


class NewDestinationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=list(ADDED_CONTACT_TYPES))
    # A mobile number or email, or for POSTAL the address's fields.
    value = serializers.JSONField()

    def validate(self, attrs):
        expected = dict if attrs["kind"] == DestinationKind.POSTAL else str
        if not isinstance(attrs["value"], expected):
            raise errors.DESTINATION_INVALID.validation_error(
                {"value": errors.DESTINATION_INVALID.message}
            )
        return attrs


class RecipientValuesSerializer(serializers.Serializer):
    recipient_id = serializers.UUIDField()
    party_taking_steps = serializers.ChoiceField(choices=Side.choices, required=False)
    channels = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    addresses = serializers.ListField(child=serializers.UUIDField(), default=list)
    new_destinations = NewDestinationSerializer(many=True, default=list)
    police_station = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class ItemValuesSerializer(serializers.Serializer):
    """The shape of a Process-category item's values (#5.1)."""

    recipients = RecipientValuesSerializer(many=True, allow_empty=False)
    notice_type = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    process_type_detail = serializers.CharField(required=False, allow_null=True, allow_blank=True)


@dataclass
class Planned:
    """One process to create.

    A destination added on the order screen has ``added`` (its value) and
    ``added_path`` (its field) set, and ``destination`` only once it is saved.
    """

    recipient: object
    recipient_type: str
    party_taking_steps: str
    channel: object
    destination: dict
    added: object = None
    added_path: str = ""


def _refuse(error, field, message=None):
    raise BusinessError(error, message, field=f"values.{field}")


def _party_taking_steps(recipient, given, path):
    side = given or default_party_taking_steps(recipient)
    if not side:
        _refuse(errors.PARTY_TAKING_STEPS_REQUIRED, f"{path}.party_taking_steps")
    return side


def _channels(process_type, codes, path):
    allowed = {
        row.channel.code: row.channel
        for row in ProcessTypeChannel.objects.active()
        .filter(process_type=process_type, channel__is_active=True, channel__is_available=True)
        .select_related("channel")
    }
    if not codes:
        _refuse(errors.CHANNEL_NOT_ALLOWED, f"{path}.channels")
    for index, code in enumerate(codes):
        if code not in allowed:
            _refuse(errors.CHANNEL_NOT_ALLOWED, f"{path}.channels[{index}]")
    return [allowed[code] for code in dict.fromkeys(codes)]


def _police_station(code, path):
    station = (
        Location.objects.active()
        .filter(code=code or "", location_type=Location.LocationType.POLICE_STATION)
        .first()
    )
    if station is None:
        _refuse(errors.POLICE_STATION_REQUIRED, f"{path}.police_station")
    return station


def _destinations(recipient, channel, values, path):
    """The channel's destinations on the record, and the ones added for it (``PRC-05``).

    Returns ``(on_record, added)``: field dicts, and ``(value, field path)`` pairs.
    """
    kind = channel.destination_kind
    if kind == DestinationKind.POLICE_STATION:
        return [{"police_station": _police_station(values.get("police_station"), path)}], []
    added = [
        (item["value"], f"{path}.new_destinations[{index}]")
        for index, item in enumerate(values["new_destinations"])
        if item["kind"] == kind
    ]
    field = DESTINATION_FIELDS[kind]
    if kind == DestinationKind.POSTAL:
        for index, address_id in enumerate(values["addresses"]):
            if address_id not in recipient.address_ids:
                _refuse(errors.NO_DESTINATION, f"{path}.addresses[{index}]")
        chosen = values["addresses"]
    else:
        # The primary number or email on the record.
        chosen = (recipient.mobiles if kind == DestinationKind.MOBILE else recipient.emails)[:1]
    if not chosen and not added:
        _refuse(
            errors.NO_DESTINATION,
            f"{path}.channels",
            f"The recipient has no destination for {channel.label}. Add one or choose another.",
        )
    return [{field: value} for value in chosen], added


def plan(case_id, process_type, values):
    """Check the item's values against the case and the masters; return what to create (#5.2).

    Writes nothing. Raises ``BusinessError`` with ``field`` under ``values``.
    """
    shape = ItemValuesSerializer(data=values)
    shape.is_valid(raise_exception=True)
    recipients = process_recipients(case_id)
    planned = []
    for index, item in enumerate(shape.validated_data["recipients"]):
        path = f"recipients[{index}]"
        recipient = recipients.get(item["recipient_id"])
        if recipient is None:
            _refuse(
                errors.RECIPIENT_NOT_ALLOWED,
                f"{path}.recipient_id",
                "Not a recipient on this case.",
            )
        kind = recipient_type(recipient)
        if kind not in process_type.allowed_recipient_types:
            _refuse(errors.RECIPIENT_NOT_ALLOWED, f"{path}.recipient_id")
        side = _party_taking_steps(recipient, item.get("party_taking_steps"), path)
        for channel in _channels(process_type, item["channels"], path):
            on_record, added = _destinations(recipient, channel, item, path)
            common = {
                "recipient": recipient,
                "recipient_type": kind,
                "party_taking_steps": side,
                "channel": channel,
            }
            planned += [Planned(**common, destination=fields) for fields in on_record]
            planned += [
                Planned(**common, destination={}, added=value, added_path=added_path)
                for value, added_path in added
            ]
    return planned


def _save_added(planned, actor):
    """Save each destination added on the order screen to the recipient's record (``PRC-05``)."""
    adding = [each for each in planned if each.added is not None]
    participants = CaseParticipant.objects.select_related("case", "institution").in_bulk(
        {each.recipient.id for each in adding}
    )
    for each in adding:
        kind = each.channel.destination_kind
        try:
            stored = add_contact(
                participants[each.recipient.id], ADDED_CONTACT_TYPES[kind], each.added, actor
            )
        except DjangoValidationError:
            _refuse(errors.DESTINATION_INVALID, each.added_path)
        each.destination = {DESTINATION_FIELDS[kind]: stored}


def _round(case_id, order_id, hearing_id):
    """The order's round; its hearing is the order's new one, else the case's next (``PRC-06``)."""
    existing = ProcessRound.objects.filter(order_id=order_id).first()
    if existing:
        return existing
    hearing = get_hearing(hearing_id) if hearing_id else next_hearing(case_id)
    summary = get_case_summaries([case_id])[case_id]
    if summary.court_id is None:
        raise BusinessError(errors.INVALID_PROCESS_ACTION, "The case has no courtroom yet.")
    return ProcessRound.objects.create(
        case_id=case_id,
        order_id=order_id,
        hearing_id=hearing.id if hearing else None,
        hearing_date=hearing.hearing_date if hearing else None,
        court_id=summary.court_id,
    )


def start_from_order_item(
    *, case_id, order_id, order_item_id, item_code, values, hearing_id=None, actor=None
) -> list[UUID]:
    """Create the item's processes; return their ids. A redelivered trigger creates nothing."""
    process_type = ProcessType.objects.active().get(order_item_code=item_code)
    with transaction.atomic():
        ProcessCaseLock.objects.get_or_create(case_id=case_id)
        ProcessCaseLock.objects.select_for_update().get(case_id=case_id)
        done = list(
            Process.objects.filter(order_item_id=order_item_id).values_list("pk", flat=True)
        )
        if done:
            return done
        planned = plan(case_id, process_type, values)
        _save_added(planned, actor)
        round_ = _round(case_id, order_id, hearing_id)
        processes = _build(planned, round_, order_item_id, process_type)
        fees.allocate(processes, case_id=case_id, order_id=order_id, actor=actor)
        for process in processes:
            process.status = steps.initial_status(process)
            process.save()
            transitions.created(process)
    return [process.pk for process in processes]


def _build(planned, round_, order_item_id, process_type):
    now = timezone.now()
    processes = {}
    for each in planned:
        process = Process(
            round=round_,
            case_id=round_.case_id,
            order_item_id=order_item_id,
            process_type=process_type,
            channel=each.channel,
            recipient_type=each.recipient_type,
            recipient_id=each.recipient.id,
            recipient_name=each.recipient.name,
            destination_kind=each.channel.destination_kind,
            destination_added=each.added is not None,
            party_taking_steps=each.party_taking_steps,
            hearing_id=round_.hearing_id,
            expires_at=expires_at(round_.hearing_date),
            status_at=now,
            **each.destination,
        )
        # A destination chosen and also added is one process (``processes_one_per_destination``).
        key = (each.recipient.id, each.channel.pk, *sorted(map(str, each.destination.items())))
        processes.setdefault(key, process)
    return list(processes.values())
