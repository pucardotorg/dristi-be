"""Hearings API serializers (spec 0023 #10.2, #10.7).

Request serializers check shape only: UUIDs, dates, enum values, lists with
no duplicates. Transitions, dates, capacity and permissions are checked by
the services under a lock. Response serializers render the dicts
``queries`` builds; nothing here touches a case model.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.api import errors as api_errors

from .enums import (
    AppearanceMode,
    AttendanceMark,
    AttendeeType,
    BulkItemResult,
    BulkMode,
    BulkRescheduleStatus,
    CalendarEntryType,
    ChangeSource,
    HearingMode,
    HearingStatus,
    RescheduleReason,
    Side,
)
from .models import CourtCalendarEntry, HearingPurpose
from .queries import ORDERINGS, QUEUE_REASONS
from .services.calendar import MAX_CALENDAR_DAYS
from .services.courtroom import BULK_ACTIONS

ORDER_FILTERS = ("NONE", "DRAFTING", "AWAITING_SIGNATURE", "ORDER_DATA_TO_FILL", "TRIGGERED")
ACTIONS = ("start", "pass_over", "end", "reschedule", "cancel", "mark_attendance")


def _no_duplicates(values, message):
    if len(values) != len({str(value).lower() for value in values}):
        raise api_errors.INVALID.validation_error(message)
    return values


@extend_schema_field(OpenApiTypes.DURATION)
class ISODurationField(serializers.Field):
    """A ``timedelta`` as an ISO 8601 duration, e.g. ``PT1H5M30S`` or ``PT0S``."""

    def to_representation(self, value):
        seconds = int(value.total_seconds())
        hours, rest = divmod(seconds, 3600)
        minutes, seconds = divmod(rest, 60)
        parts = [f"{hours}H" if hours else "", f"{minutes}M" if minutes else ""]
        parts.append(f"{seconds}S" if seconds or not (hours or minutes) else "")
        return "PT" + "".join(parts)

    def to_internal_value(self, data):
        raise NotImplementedError


# References


class PurposeSerializer(serializers.ModelSerializer):
    """An active hearing purpose, for the dropdowns (#10.4.5)."""

    class Meta:
        model = HearingPurpose
        fields = ("code", "label", "description", "sequence")
        read_only_fields = fields


class PurposeRefSerializer(serializers.Serializer):
    code = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)


class StageSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)


class CaseRefSerializer(serializers.Serializer):
    """What a hearing shows of its case, read through the cases contract."""

    id = serializers.UUIDField(read_only=True)
    display_number = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    stage = StageSerializer(read_only=True, allow_null=True)
    days_since_filing = serializers.IntegerField(read_only=True, allow_null=True)
    beyond_trial_target = serializers.BooleanField(read_only=True)


class AdvocateRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    side = serializers.ChoiceField(choices=(Side.COMPLAINANT, Side.ACCUSED), read_only=True)


class AdjournmentsSerializer(serializers.Serializer):
    COMPLAINANT = serializers.IntegerField(read_only=True)
    ACCUSED = serializers.IntegerField(read_only=True)
    COURT = serializers.IntegerField(read_only=True)


class HearingRefSerializer(serializers.Serializer):
    """The hearing before or after this one (``HRG-09``, ``HRG-10``)."""

    id = serializers.UUIDField(read_only=True)
    hearing_date = serializers.DateField(read_only=True)
    purpose = PurposeRefSerializer(read_only=True)
    status = serializers.ChoiceField(choices=HearingStatus.choices, read_only=True)


# The hearing (#10.2)


class HearingSerializer(serializers.Serializer):
    """A hearing as every hearing endpoint returns it (#10.2).

    ``allowed_actions`` is what the caller's roles in the hearing's court let
    them do now; parties never receive it.
    """

    id = serializers.UUIDField(source="hearing.pk", read_only=True)
    court = serializers.UUIDField(source="hearing.court_id", read_only=True)
    hearing_date = serializers.DateField(source="hearing.hearing_date", read_only=True)
    sequence = serializers.IntegerField(source="hearing.sequence", read_only=True, allow_null=True)
    status = serializers.ChoiceField(
        source="hearing.status", choices=HearingStatus.choices, read_only=True
    )
    mode = serializers.ChoiceField(
        source="hearing.mode", choices=HearingMode.choices, read_only=True
    )
    purpose = PurposeRefSerializer(source="hearing.purpose", read_only=True)
    case = CaseRefSerializer(read_only=True, allow_null=True)
    advocates = AdvocateRefSerializer(many=True, read_only=True)
    original_date = serializers.DateField(source="hearing.original_date", read_only=True)
    reschedule_count = serializers.IntegerField(source="hearing.reschedule_count", read_only=True)
    adjournments = AdjournmentsSerializer(read_only=True)
    started_at = serializers.DateTimeField(source="hearing.started_at", read_only=True)
    ended_at = serializers.DateTimeField(source="hearing.ended_at", read_only=True)
    heard_duration = ISODurationField(source="hearing.heard_duration", read_only=True)
    adjournment_sought_by = serializers.CharField(
        source="hearing.adjournment_sought_by", read_only=True
    )
    order_id = serializers.UUIDField(source="hearing.order_id", read_only=True, allow_null=True)
    cancellation_reason = serializers.CharField(
        source="hearing.cancellation_reason", read_only=True
    )
    allowed_actions = serializers.ListField(
        child=serializers.ChoiceField(choices=ACTIONS), read_only=True, required=False
    )
    updated_at = serializers.DateTimeField(source="hearing.updated_at", read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if "allowed_actions" not in instance:
            data.pop("allowed_actions", None)
        return data


class AttendanceMarkSerializer(serializers.Serializer):
    attendee_type = serializers.ChoiceField(choices=AttendeeType.choices, read_only=True)
    participant_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    mark = serializers.ChoiceField(choices=AttendanceMark.choices, read_only=True)
    appearance_mode = serializers.CharField(read_only=True)


class AttendanceSerializer(serializers.Serializer):
    """The marks, whether the roll is complete and locked, and the line for view case (HRG-08)."""

    marks = AttendanceMarkSerializer(many=True, read_only=True)
    complete = serializers.BooleanField(read_only=True)
    locked = serializers.BooleanField(read_only=True)
    line = serializers.CharField(read_only=True)


class DateChangeSerializer(serializers.Serializer):
    from_date = serializers.DateField(read_only=True)
    to_date = serializers.DateField(read_only=True)
    from_purpose = PurposeRefSerializer(read_only=True)
    to_purpose = PurposeRefSerializer(read_only=True)
    reason_code = serializers.ChoiceField(choices=RescheduleReason.choices, read_only=True)
    reason_text = serializers.CharField(read_only=True)
    sought_by = serializers.ChoiceField(choices=Side.choices, read_only=True)
    source = serializers.ChoiceField(choices=ChangeSource.choices, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class HearingDetailSerializer(HearingSerializer):
    """A hearing with its attendance, date changes and the hearings before and after (#10.2)."""

    attendance = AttendanceSerializer(read_only=True)
    date_changes = DateChangeSerializer(many=True, read_only=True)
    previous_hearing = HearingRefSerializer(read_only=True, allow_null=True)
    next_hearing = HearingRefSerializer(read_only=True, allow_null=True)


class WarningSerializer(serializers.Serializer):
    """A soft problem: accepted, but worth showing (#4, #10.6)."""

    code = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    detail = serializers.DictField(read_only=True)


class HearingMovedSerializer(HearingSerializer):
    """A moved hearing, with the move's warnings (a full day, the adjournment limit)."""

    warnings = WarningSerializer(many=True, read_only=True)


class NextHearingSerializer(serializers.Serializer):
    """The next hearing tile: the hearing in progress, else the scheduled one, else null."""

    hearing = HearingSerializer(read_only=True, allow_null=True)


# Lists and counts


class BoardQuerySerializer(serializers.Serializer):
    """Filters of the board and search (#10.3)."""

    court = serializers.UUIDField()
    date = serializers.ListField(child=serializers.DateField(), required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    status = serializers.ListField(
        child=serializers.ChoiceField(choices=HearingStatus.choices), required=False
    )
    purpose = serializers.ListField(child=serializers.CharField(), required=False)
    advocate = serializers.ListField(child=serializers.UUIDField(), required=False)
    has_order = serializers.ListField(
        child=serializers.ChoiceField(choices=ORDER_FILTERS),
        required=False,
        help_text="Only NONE for now; order statuses need the orders module.",
    )
    stage = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Not available until case stages are modelled.",
    )
    case = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True)
    not_reached = serializers.BooleanField(required=False, default=False)
    beyond_trial_target = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="true: cases older than the trial target (§143(3) NI Act); false: the rest.",
    )
    changed_since = serializers.DateTimeField(required=False)
    ordering = serializers.ChoiceField(
        choices=[*ORDERINGS, *(f"-{key}" for key in ORDERINGS)], required=False
    )

    def validate_has_order(self, value):
        if any(choice != "NONE" for choice in value):
            raise api_errors.INVALID.validation_error(
                "Only NONE can be filtered on for now; order statuses need the orders module."
            )
        return value

    def validate_stage(self, value):
        if value:
            raise api_errors.INVALID.validation_error(
                "Filtering by case stage is not available until case stages are recorded."
            )
        return value

    def validate(self, attrs):
        date_from, date_to = attrs.get("date_from"), attrs.get("date_to")
        if date_from and date_to:
            if date_to < date_from:
                raise api_errors.INVALID.validation_error(
                    {"date_to": "The end date must be on or after the start date."}
                )
            if (date_to - date_from).days + 1 > MAX_CALENDAR_DAYS:
                raise api_errors.INVALID.validation_error(
                    {"date_to": f"Ask for at most {MAX_CALENDAR_DAYS} days at a time."}
                )
        return attrs


class CourtQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()


class CountsSerializer(serializers.Serializer):
    """Badge counts (#10.4.4)."""

    today = serializers.IntegerField(read_only=True)
    by_status = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    not_reached = serializers.IntegerField(read_only=True)
    scheduling_queue = serializers.IntegerField(read_only=True)
    stale_holds = serializers.IntegerField(read_only=True)


class QueueItemSerializer(serializers.Serializer):
    """A case waiting for a date (#10.4.8)."""

    case = CaseRefSerializer(read_only=True)
    advocates = AdvocateRefSerializer(many=True, read_only=True)
    waiting_since = serializers.DateTimeField(read_only=True, allow_null=True)
    reason = serializers.ChoiceField(choices=QUEUE_REASONS, read_only=True)


# Courtroom actions (#6)


class EndSerializer(serializers.Serializer):
    adjournment_sought_by = serializers.ChoiceField(
        choices=Side.choices,
        required=False,
        allow_blank=True,
        default="",
        help_text="Who sought the adjournment; leave empty when business was done.",
    )


class BulkActionSerializer(serializers.Serializer):
    court = serializers.UUIDField()
    hearing_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    action = serializers.ChoiceField(choices=BULK_ACTIONS)

    def validate_hearing_ids(self, value):
        return _no_duplicates(value, "List each hearing once.")


class BulkDoneSerializer(serializers.Serializer):
    hearing_id = serializers.UUIDField(read_only=True)
    status = serializers.ChoiceField(choices=HearingStatus.choices, read_only=True)


class BulkSkippedSerializer(serializers.Serializer):
    hearing_id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True, help_text="Why it was left as it is.")
    allowed_actions = serializers.ListField(child=serializers.CharField(), read_only=True)


class BulkActionResultSerializer(serializers.Serializer):
    done = BulkDoneSerializer(many=True, read_only=True)
    skipped = BulkSkippedSerializer(many=True, read_only=True)


class MarkSerializer(serializers.Serializer):
    attendee_type = serializers.ChoiceField(choices=AttendeeType.choices)
    participant_id = serializers.UUIDField()
    mark = serializers.ChoiceField(choices=AttendanceMark.choices)
    appearance_mode = serializers.ChoiceField(
        choices=AppearanceMode.choices, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        present = attrs["mark"] == AttendanceMark.PRESENT
        if present and not attrs["appearance_mode"]:
            raise api_errors.INVALID.validation_error(
                {"appearance_mode": "Choose in person or video for someone marked present."}
            )
        if not present and attrs["appearance_mode"]:
            raise api_errors.INVALID.validation_error(
                {"appearance_mode": "Leave it empty for someone absent or not required."}
            )
        return attrs


class AttendanceInputSerializer(serializers.Serializer):
    """The whole roll; anyone left out is unmarked (#6.5)."""

    marks = MarkSerializer(many=True)

    def validate_marks(self, value):
        keys = [(mark["attendee_type"], str(mark["participant_id"])) for mark in value]
        if len(keys) != len(set(keys)):
            raise api_errors.INVALID.validation_error("Mark each person once.")
        return value


class ReorderSerializer(serializers.Serializer):
    court = serializers.UUIDField()
    hearing_date = serializers.DateField()
    hearing_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)

    def validate_hearing_ids(self, value):
        return _no_duplicates(value, "List each hearing once.")


# Moves (#8)


class RescheduleSerializer(serializers.Serializer):
    hearing_date = serializers.DateField()
    purpose = serializers.CharField(required=False, help_text="A purpose code; omit to keep it.")
    reason_code = serializers.ChoiceField(choices=RescheduleReason.choices)
    reason_text = serializers.CharField(required=False, allow_blank=True, default="")


class BulkPreviewSerializer(serializers.Serializer):
    court = serializers.UUIDField()
    hearing_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    mode = serializers.ChoiceField(choices=BulkMode.choices)
    target_date = serializers.DateField(required=False, allow_null=True)
    schedule_after = serializers.DateField(required=False, allow_null=True)
    block_source_dates = serializers.BooleanField(required=False, default=False)
    reason_code = serializers.ChoiceField(
        choices=RescheduleReason.choices,
        help_text="A court-side reason; party and judicial reasons need an order (E10013).",
    )
    reason_text = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_hearing_ids(self, value):
        return _no_duplicates(value, "List each hearing once.")


class PreviewLineSerializer(serializers.Serializer):
    hearing_id = serializers.UUIDField(read_only=True)
    from_date = serializers.DateField(read_only=True)
    to_date = serializers.DateField(read_only=True)


class PreviewLoadSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    capacity = serializers.IntegerField(read_only=True)
    provisional = serializers.IntegerField(read_only=True)
    listed_before = serializers.IntegerField(read_only=True)
    listed_after = serializers.IntegerField(read_only=True)


class BulkPreviewResultSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(source="job.pk", read_only=True)
    status = serializers.ChoiceField(
        source="job.status", choices=BulkRescheduleStatus.choices, read_only=True
    )
    preview_expires_at = serializers.DateTimeField(source="job.preview_expires_at", read_only=True)
    lines = PreviewLineSerializer(many=True, read_only=True)
    loads = PreviewLoadSerializer(many=True, read_only=True)
    warnings = WarningSerializer(
        many=True, read_only=True, help_text="A target day taken past its capacity (warn mode)."
    )


class BulkConfirmedSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(source="pk", read_only=True)
    status = serializers.ChoiceField(choices=BulkRescheduleStatus.choices, read_only=True)


class BulkItemSerializer(serializers.Serializer):
    hearing_id = serializers.UUIDField(read_only=True)
    from_date = serializers.DateField(read_only=True)
    to_date = serializers.DateField(read_only=True)
    result = serializers.ChoiceField(choices=BulkItemResult.choices, read_only=True)
    error_code = serializers.CharField(read_only=True)


class BulkJobSerializer(serializers.Serializer):
    """A bulk move and what became of each hearing in it (#8.3)."""

    job_id = serializers.UUIDField(source="pk", read_only=True)
    court = serializers.UUIDField(source="court_id", read_only=True)
    mode = serializers.ChoiceField(choices=BulkMode.choices, read_only=True)
    target_date = serializers.DateField(read_only=True)
    schedule_after = serializers.DateField(read_only=True)
    block_source_dates = serializers.BooleanField(read_only=True)
    reason_code = serializers.ChoiceField(choices=RescheduleReason.choices, read_only=True)
    reason_text = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=BulkRescheduleStatus.choices, read_only=True)
    preview_expires_at = serializers.DateTimeField(read_only=True)
    confirmed_at = serializers.DateTimeField(read_only=True)
    items = BulkItemSerializer(many=True, read_only=True, source="items.all")


# Calendar (#9)


class CalendarQuerySerializer(serializers.Serializer):
    """``?from=&to=``; ``from`` defaults to today, ``to`` to 30 days on."""

    to = serializers.DateField(required=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = serializers.DateField(required=False)
        return fields


class CalendarEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CourtCalendarEntry
        fields = ("id", "date", "entry_type", "reason", "capacity_override")
        read_only_fields = fields


class CalendarEntryRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    entry_type = serializers.ChoiceField(choices=CalendarEntryType.choices, read_only=True)
    reason = serializers.CharField(read_only=True)


class PurposeLoadSerializer(serializers.Serializer):
    purpose = PurposeRefSerializer(read_only=True)
    listed = serializers.IntegerField(read_only=True)
    provisional = serializers.IntegerField(read_only=True)


class CalendarDaySerializer(serializers.Serializer):
    """One day of the date picker (#9.1)."""

    date = serializers.DateField(read_only=True)
    sitting = serializers.BooleanField(read_only=True)
    capacity = serializers.IntegerField(read_only=True)
    listed = serializers.IntegerField(read_only=True)
    provisional = serializers.IntegerField(read_only=True)
    by_purpose = PurposeLoadSerializer(many=True, read_only=True)
    entry = CalendarEntryRefSerializer(read_only=True, allow_null=True)


class CalendarEntryCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    entry_type = serializers.ChoiceField(choices=CalendarEntryType.choices)
    reason = serializers.CharField(max_length=255)
    capacity_override = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Hearings the court can take that day; only for a reduced sitting.",
    )

    def validate(self, attrs):
        reduced = attrs["entry_type"] == CalendarEntryType.REDUCED_SITTING
        capacity = attrs.get("capacity_override")
        if reduced and not capacity:
            raise api_errors.INVALID.validation_error(
                {"capacity_override": "Enter a capacity of at least 1 for a reduced sitting."}
            )
        if not reduced and capacity is not None:
            raise api_errors.INVALID.validation_error(
                {"capacity_override": "Capacity can be set only for a reduced sitting."}
            )
        return attrs


class BusinessDateSerializer(serializers.Serializer):
    """The court's today, whether it sits and when parties report (#9.3)."""

    business_date = serializers.DateField(read_only=True)
    timezone = serializers.CharField(read_only=True)
    sitting = serializers.BooleanField(read_only=True)
    sitting_time = serializers.CharField(read_only=True)
