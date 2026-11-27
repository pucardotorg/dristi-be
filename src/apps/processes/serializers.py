"""Processes API serializers (spec 0028 #11).

Input serializers check shape only; the services check actions, transitions
and reasons under the process lock (#11.6). Output is read only.

``ProcessSerializer`` reads three things from its context, prepared once per
response by the view: ``user`` (for ``allowed_actions``), ``cases`` (case
summaries by id) and ``hearing_dates`` (each hearing's current date by id).
"""

import datetime

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.cases.serializers import AddressSerializer, CodeLabelSerializer
from apps.files.documents import document_error

from . import steps
from .enums import OUTCOME_STATUS_CHOICES, ProcessStatus, RecipientType, SendAct, Side
from .models import Channel, NonDeliveryReason, ProcessEvent, ProcessType

# Input


class OptionalBooleanField(serializers.BooleanField):
    """A query flag that filters only when given: absent is neither true nor false."""

    default_empty_html = serializers.empty


class ListQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=ProcessStatus.choices), required=False
    )
    process_type = serializers.ListField(child=serializers.CharField(), required=False)
    channel = serializers.ListField(child=serializers.CharField(), required=False)
    reason = serializers.ListField(child=serializers.CharField(), required=False)
    my_move = serializers.BooleanField(required=False, default=False)
    # Its envelope is still to be received (RPAD and Police (RPAD), ``STP-02``).
    envelope_due = OptionalBooleanField(required=False)
    fee_paid = OptionalBooleanField(required=False)
    case = serializers.UUIDField(required=False)
    round = serializers.UUIDField(required=False)
    hearing = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True)
    ordering = serializers.ChoiceField(
        choices=[
            f"{sign}{field}"
            for field in ("status_at", "hearing_date", "expires_at", "created_at")
            for sign in ("", "-")
        ],
        required=False,
    )


class CourtQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()


class ReasonQuerySerializer(serializers.Serializer):
    # Only the reasons for this process type, e.g. ``WARRANT``.
    process_type = serializers.CharField(required=False)


class SendSerializer(serializers.Serializer):
    # A by-hand proclamation: sent and executed at once (``DSP-10``).
    published = serializers.BooleanField(required=False, default=False)


class OutcomeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OUTCOME_STATUS_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    outcome_date = serializers.DateField(required=False, allow_null=True, default=None)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    file_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)


class OutcomeFileSerializer(serializers.Serializer):
    """A supporting file for an outcome: the acknowledgement card, a report (``DSP-08``)."""

    file = serializers.FileField()

    def validate_file(self, upload):
        error = document_error(upload)
        if error:
            raise serializers.ValidationError(error[0].upper() + error[1:])
        return upload


class OutcomeFileResultSerializer(serializers.Serializer):
    """Pass ``file_id`` as the outcome's ``file_id``."""

    file_id = serializers.UUIDField()


def _once_each(ids):
    if len(set(ids)) != len(ids):
        raise serializers.ValidationError("List each process once.")
    return ids


class ProcessIdsSerializer(serializers.Serializer):
    """A selection of processes for one step (receive envelopes, mark sent)."""

    process_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)

    def validate_process_ids(self, value):
        return _once_each(value)


class RecallSerializer(ProcessIdsSerializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class OutcomeItemSerializer(OutcomeSerializer):
    """One return in a batch; its ``outcome_date``, if given, overrides the batch's."""

    process_id = serializers.UUIDField()


class OutcomesSerializer(serializers.Serializer):
    """A pile of returns recorded together, on the day they came back (``DSP-08``)."""

    outcome_date = serializers.DateField(required=False, allow_null=True, default=None)
    outcomes = OutcomeItemSerializer(many=True, allow_empty=False)

    def validate_outcomes(self, value):
        _once_each([each["process_id"] for each in value])
        return value


# Output


class ChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Channel
        fields = ("code", "label", "destination_kind", "send_mode", "status_mode", "needs_envelope")


class ProcessCaseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_number = serializers.CharField()
    title = serializers.CharField()


class ProcessRoundSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_id = serializers.UUIDField()


class ProcessHearingSerializer(serializers.Serializer):
    """The hearing's date at issue and its current date (#7.3); read from a process."""

    id = serializers.UUIDField(source="hearing_id")
    date_at_issue = serializers.DateField(source="round.hearing_date")
    current_date = serializers.SerializerMethodField()

    def get_current_date(self, process) -> datetime.date | None:
        return self.context["hearing_dates"].get(process.hearing_id)


class ProcessRecipientSerializer(serializers.Serializer):
    """Who a process names; read from a process."""

    id = serializers.UUIDField(source="recipient_id")
    type = serializers.CharField(source="recipient_type")
    name = serializers.CharField(source="recipient_name")


class PoliceStationSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()


class ProcessDestinationSerializer(serializers.Serializer):
    """Where a process goes; read from a process."""

    kind = serializers.CharField(source="destination_kind")
    address_id = serializers.UUIDField()
    mobile = serializers.CharField()
    email = serializers.CharField()
    police_station = PoliceStationSerializer(allow_null=True)
    added = serializers.BooleanField(source="destination_added")


class ProcessFeeSerializer(serializers.Serializer):
    court_fee = serializers.DecimalField(max_digits=18, decimal_places=2)
    paid = serializers.BooleanField(source="fee_paid")
    paid_at = serializers.DateTimeField(source="fee_paid_at")


@extend_schema_field(ProcessHearingSerializer(allow_null=True))
class ProcessHearingField(serializers.Field):
    """A process's hearing, or null when it has none."""

    def __init__(self, source="*", **kwargs):
        super().__init__(source=source, read_only=True, **kwargs)

    def to_representation(self, process):
        if process.hearing_id is None:
            return None
        return ProcessHearingSerializer(process, context=self.context).data


class ProcessSerializer(serializers.Serializer):
    """One process as the lists, the register and the detail show it."""

    id = serializers.UUIDField()
    case = serializers.SerializerMethodField()
    round = ProcessRoundSerializer()
    hearing = ProcessHearingField()
    process_type = CodeLabelSerializer()
    recipient = ProcessRecipientSerializer(source="*")
    channel = ChannelSerializer()
    destination = ProcessDestinationSerializer(source="*")
    party_taking_steps = serializers.CharField()
    # The order item's other fields, e.g. ``warrant_type``, ``bond_amount``, ``sureties`` (``TPL-04``).
    item_fields = serializers.DictField(read_only=True)
    status = serializers.CharField()
    status_label = serializers.CharField()
    status_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    fee = ProcessFeeSerializer(source="*")
    # Each stage's own time (``SGN-04``); the fee's is ``fee.paid_at``.
    envelope_received_at = serializers.DateTimeField()
    signed_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField()
    reason = CodeLabelSerializer(allow_null=True)
    remark = serializers.CharField()
    outcome_date = serializers.DateField()
    outcome_file_id = serializers.CharField()
    signed_file_id = serializers.CharField()
    allowed_actions = serializers.SerializerMethodField()
    # What ``send`` in ``allowed_actions`` is on the screen: posted, handed over, published.
    send_act = serializers.ChoiceField(choices=SendAct.choices, read_only=True)

    @extend_schema_field(ProcessCaseSerializer)
    def get_case(self, process):
        summary = self.context["cases"].get(process.case_id)
        return {
            "id": process.case_id,
            "display_number": summary.display_number if summary else "",
            "title": summary.title if summary else "",
        }

    def get_allowed_actions(self, process) -> list[str]:
        return [str(step) for step in steps.allowed_steps(self.context["user"], process)]


class ProcessEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessEvent
        fields = ("from_status", "to_status", "source", "actor", "at", "data")


class ProcessDetailSerializer(ProcessSerializer):
    """One process with its history."""

    recalled_at = serializers.DateTimeField()
    events = ProcessEventSerializer(many=True)


class ProcessRegisterGroupSerializer(serializers.Serializer):
    """One round's processes of one type (``SVC-05``–``SVC-08``, ``SVC-19``)."""

    process_type = CodeLabelSerializer(source="first.process_type")
    round = ProcessRoundSerializer(source="first.round")
    hearing = ProcessHearingField(source="first")
    processes = ProcessSerializer(many=True)


class ProcessRegisterEntrySerializer(serializers.Serializer):
    """One person on the case and their processes (``SVC-01``–``SVC-03``)."""

    recipient = ProcessRecipientSerializer()
    groups = ProcessRegisterGroupSerializer(many=True)


class ProcessCountCellSerializer(serializers.Serializer):
    status = serializers.CharField()
    channel = serializers.CharField()
    process_type = serializers.CharField()
    count = serializers.IntegerField()


class ProcessCountsSerializer(serializers.Serializer):
    by_status = serializers.DictField(child=serializers.IntegerField())
    by_channel = serializers.DictField(child=serializers.IntegerField())
    # ``{status: {channel: n}}``: a pill that is one status on some channels.
    by_status_channel = serializers.DictField(
        child=serializers.DictField(child=serializers.IntegerField())
    )
    # Every status, channel and type counted together: a pill that also splits by type.
    breakdown = ProcessCountCellSerializer(many=True)
    my_moves = serializers.IntegerField()


class BulkResultSerializer(serializers.Serializer):
    """A step on a selection: the processes it was taken on, and those it no longer applied to."""

    done = ProcessSerializer(many=True)
    skipped = ProcessSerializer(many=True)


class OrderRecipientSerializer(serializers.Serializer):
    """A recipient the order screen offers, with destinations and defaults (#5.4)."""

    id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=RecipientType.choices)
    name = serializers.CharField()
    # Null where it cannot be worked out and must be chosen (``AUT-03``).
    party_taking_steps = serializers.ChoiceField(choices=Side.choices, allow_null=True)
    preselected = serializers.BooleanField()
    mobiles = serializers.ListField(child=serializers.CharField())
    emails = serializers.ListField(child=serializers.CharField())
    addresses = AddressSerializer(many=True)
    # The station used for them in an earlier round, to pre-fill (``AUT-04``).
    police_station = PoliceStationSerializer(allow_null=True)


class OfferedChannelSerializer(ChannelSerializer):
    """A channel offered for a process type, and whether it is preselected (``AUT-08``)."""

    preselected = serializers.BooleanField()

    class Meta(ChannelSerializer.Meta):
        fields = (*ChannelSerializer.Meta.fields, "preselected")


class ProcessTypeSerializer(serializers.ModelSerializer):
    channels = serializers.SerializerMethodField()

    class Meta:
        model = ProcessType
        fields = (
            "code",
            "label",
            "positive_label",
            "negative_label",
            "allowed_recipient_types",
            "channels",
        )

    @extend_schema_field(OfferedChannelSerializer(many=True))
    def get_channels(self, process_type):
        """The channels this deployment offers for the type."""
        offered = []
        for row in process_type.type_channels.all():
            if row.is_active and row.channel.is_active and row.channel.is_available:
                row.channel.preselected = row.preselected
                offered.append(row.channel)
        return OfferedChannelSerializer(offered, many=True).data


class NonDeliveryReasonSerializer(serializers.ModelSerializer):
    # The process types it is for; empty for every type.
    process_types = serializers.SlugRelatedField(slug_field="code", many=True, read_only=True)

    class Meta:
        model = NonDeliveryReason
        fields = ("code", "label", "process_types")
