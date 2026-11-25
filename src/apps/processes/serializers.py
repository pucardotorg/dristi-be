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

from apps.cases.serializers import CodeLabelSerializer

from . import steps
from .enums import OUTCOME_STATUSES, ProcessStatus
from .models import Channel, NonDeliveryReason, ProcessEvent, ProcessType

# Input


class ListQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=ProcessStatus.choices), required=False
    )
    process_type = serializers.ListField(child=serializers.CharField(), required=False)
    channel = serializers.ListField(child=serializers.CharField(), required=False)
    reason = serializers.ListField(child=serializers.CharField(), required=False)
    my_move = serializers.BooleanField(required=False, default=False)
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


class SendSerializer(serializers.Serializer):
    # A by-hand proclamation: sent and executed at once (``DSP-10``).
    published = serializers.BooleanField(required=False, default=False)


class OutcomeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[(status.value, status.label) for status in OUTCOME_STATUSES]
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    outcome_date = serializers.DateField(required=False, allow_null=True, default=None)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    file_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=64)


class RecallSerializer(serializers.Serializer):
    process_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate_process_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("List each process once.")
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
    status = serializers.CharField()
    status_label = serializers.CharField()
    status_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    fee = ProcessFeeSerializer(source="*")
    reason = CodeLabelSerializer(allow_null=True)
    remark = serializers.CharField()
    outcome_date = serializers.DateField()
    outcome_file_id = serializers.CharField()
    signed_file_id = serializers.CharField()
    allowed_actions = serializers.SerializerMethodField()

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

    envelope_received_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField()
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


class ProcessCountsSerializer(serializers.Serializer):
    by_status = serializers.DictField(child=serializers.IntegerField())
    by_channel = serializers.DictField(child=serializers.IntegerField())
    my_moves = serializers.IntegerField()


class RecallResultSerializer(serializers.Serializer):
    recalled = ProcessSerializer(many=True)
    skipped = ProcessSerializer(many=True)


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
    class Meta:
        model = NonDeliveryReason
        fields = ("code", "label")
