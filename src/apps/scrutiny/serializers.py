"""Scrutiny API serializers (spec 0024 #7, #8).

Request serializers validate bodies and query parameters; the services apply
the business rules. Response serializers render the read models of
``selectors`` (plain dicts), so their shapes are documented in Swagger.
"""

from rest_framework import serializers

from apps.cases.models import CaseStatus

from . import selectors
from .enums import DocumentIssue, FlagStatus, FlagTarget, ResponseKind, RoundDecision, RoundStage

# Requests


class ScrutinyListQuerySerializer(serializers.Serializer):
    """Query parameters of the scrutiny list (#7.1)."""

    tab = serializers.ChoiceField(choices=selectors.TABS, default="registry")
    claimed = serializers.ChoiceField(choices=selectors.CLAIMED, default="anyone")
    search = serializers.CharField(required=False, allow_blank=True, default="")
    establishment = serializers.UUIDField(required=False, allow_null=True, default=None)


class DocumentIssueSerializer(serializers.Serializer):
    """A document issue saved with a field flag (*Save both*)."""

    document_id = serializers.UUIDField()
    reason_code = serializers.ChoiceField(
        choices=DocumentIssue.choices, required=False, allow_blank=True, default=""
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")


class FlagCreateSerializer(serializers.Serializer):
    """POST /scrutiny/{case_id}/flags/ (#8.1)."""

    target_type = serializers.ChoiceField(choices=FlagTarget.choices)
    target_ref = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    reason_code = serializers.ChoiceField(
        choices=DocumentIssue.choices, required=False, allow_blank=True, default=""
    )
    document_issue = DocumentIssueSerializer(required=False, allow_null=True, default=None)


class FlagUpdateSerializer(serializers.Serializer):
    """PATCH /scrutiny/{case_id}/flags/{flag_id}/: a draft's note or reason."""

    note = serializers.CharField(required=False, allow_blank=True)
    reason_code = serializers.ChoiceField(
        choices=DocumentIssue.choices, required=False, allow_blank=True
    )


class MoveOnSerializer(serializers.Serializer):
    """Forward or register at Scrutiny (#4.4)."""

    # Optional where the establishment has one courtroom.
    courtroom_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    # Optional where the state has one registration type.
    registration_type = serializers.CharField(
        required=False, allow_blank=True, max_length=32, default=""
    )
    acknowledge_open_items = serializers.BooleanField(required=False, default=False)


class TitleSerializer(serializers.Serializer):
    """PATCH /scrutiny/{case_id}/title/: the parties' display names (#4.6)."""

    complainant = serializers.CharField(max_length=256)
    accused = serializers.CharField(max_length=256)


# Responses: shared pieces


class PersonSerializer(serializers.Serializer):
    """A court user or filer, by name."""

    id = serializers.UUIDField()
    name = serializers.CharField()


class NamedSerializer(serializers.Serializer):
    """A courtroom."""

    id = serializers.UUIDField()
    name = serializers.CharField()


class RegistrationTypeSerializer(serializers.Serializer):
    """One of the state's registration types (``SCR-13``)."""

    code = serializers.CharField()
    label = serializers.CharField()


class CaseTypeSerializer(serializers.Serializer):
    """A case type key and its label."""

    key = serializers.CharField()
    label = serializers.CharField()


class FlagResponseSerializer(serializers.Serializer):
    """The filer's answer to a flag (#3.6)."""

    kind = serializers.ChoiceField(choices=ResponseKind.choices)
    note = serializers.CharField()
    value_after = serializers.JSONField(allow_null=True)
    document_id = serializers.UUIDField(allow_null=True)
    responded_at = serializers.DateTimeField()
    contested = serializers.BooleanField(help_text="Explained without a change.")


class FlagHistorySerializer(serializers.Serializer):
    """An earlier copy of a carried item."""

    flag_id = serializers.UUIDField()
    round = serializers.IntegerField()
    stage = serializers.ChoiceField(choices=RoundStage.choices)
    note = serializers.CharField()
    status = serializers.ChoiceField(choices=FlagStatus.choices)
    responses = FlagResponseSerializer(many=True)


class FlagSerializer(serializers.Serializer):
    """A flag, with the filer's answers and its copies in earlier rounds."""

    id = serializers.UUIDField()
    target_type = serializers.ChoiceField(choices=FlagTarget.choices)
    target_ref = serializers.CharField()
    target_label = serializers.CharField()
    section_id = serializers.CharField()
    reason_code = serializers.CharField()
    note = serializers.CharField()
    value_at_flag = serializers.JSONField(allow_null=True)
    status = serializers.ChoiceField(choices=FlagStatus.choices)
    auto_marked_by = serializers.UUIDField(allow_null=True)
    linked_flag = serializers.UUIDField(allow_null=True)
    carried_from = serializers.UUIDField(allow_null=True)
    resolved_at = serializers.DateTimeField(allow_null=True)
    responses = FlagResponseSerializer(many=True)
    history = FlagHistorySerializer(many=True, help_text="Earlier copies, newest first.")


class RoundSerializer(serializers.Serializer):
    """A round after an action on it."""

    id = serializers.UUIDField()
    stage = serializers.ChoiceField(choices=RoundStage.choices)
    number = serializers.IntegerField()
    started_by = PersonSerializer(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    decision = serializers.ChoiceField(choices=RoundDecision.choices, allow_blank=True)
    decided_at = serializers.DateTimeField(allow_null=True)
    courtroom_id = serializers.UUIDField(allow_null=True)
    registration_type = serializers.CharField()
    open_items_at_decision = serializers.IntegerField()


class ScrutinyDecisionSerializer(serializers.Serializer):
    """The decided round and where it left the case."""

    round = RoundSerializer()
    case_status = serializers.ChoiceField(choices=CaseStatus.choices)
    case_number = serializers.CharField(allow_null=True)
    workflow_version = serializers.IntegerField()


# Responses: list (#7.1)


class ScrutinyRowSerializer(serializers.Serializer):
    """One row of the scrutiny list."""

    case_id = serializers.UUIDField()
    filing_number = serializers.CharField(allow_null=True)
    parties = serializers.CharField()
    case_type = CaseTypeSerializer()
    stage = serializers.ChoiceField(choices=selectors.LIST_STAGES)
    stage_label = serializers.CharField()
    reason = serializers.CharField()
    advocate = serializers.CharField(allow_null=True)
    # The officer working it. ``with`` is a keyword, so it is declared this way.
    locals()["with"] = PersonSerializer(allow_null=True)
    waiting_days = serializers.IntegerField()
    round = serializers.IntegerField()
    task_id = serializers.UUIDField(allow_null=True)


# Responses: scrutiny detail (#7.2)


class DetailCaseSerializer(serializers.Serializer):
    """The detail's header."""

    id = serializers.UUIDField()
    filing_number = serializers.CharField(allow_null=True)
    parties = serializers.CharField()
    submitted_at = serializers.DateField(allow_null=True)
    advocate = serializers.CharField(allow_null=True)


class DetailRoundSerializer(serializers.Serializer):
    """The round on screen."""

    id = serializers.UUIDField()
    stage = serializers.ChoiceField(choices=RoundStage.choices)
    number = serializers.IntegerField()
    started_by = PersonSerializer(allow_null=True)
    summary = serializers.CharField(help_text='"3 rounds · 1 item open since 7 Jul"')


class FieldSerializer(serializers.Serializer):
    """One filed value and the document it was read from."""

    ref = serializers.CharField()
    label = serializers.CharField()
    value = serializers.JSONField(allow_null=True)
    source_document_id = serializers.UUIDField(allow_null=True)
    flag_id = serializers.UUIDField(allow_null=True)


class FieldGroupSerializer(serializers.Serializer):
    """The fields of one record: *Cheque 1*, or the section itself."""

    title = serializers.CharField()
    fields = FieldSerializer(many=True)


class SectionSerializer(serializers.Serializer):
    """A section of the filing form."""

    id = serializers.CharField()
    title = serializers.CharField()
    groups = FieldGroupSerializer(many=True)


class BundleItemSerializer(serializers.Serializer):
    """One numbered document of the case bundle."""

    no = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=("GENERATED", "SCAN"))
    name = serializers.CharField()
    document_id = serializers.UUIDField()
    poor_scan = serializers.BooleanField()
    flag_id = serializers.UUIDField(allow_null=True)


class AlertSerializer(serializers.Serializer):
    """An advisory check; never blocks an action (``SCR-05a``)."""

    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=("INFO", "WARNING"))
    field_refs = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField()


class DetailFlagsSerializer(serializers.Serializer):
    """The round's flags, as the *Raised with* panel splits them."""

    draft = FlagSerializer(many=True)
    carried = FlagSerializer(many=True)
    raised_last_round = FlagSerializer(many=True)


class ScrutinyDetailSerializer(serializers.Serializer):
    """GET /scrutiny/{case_id}/."""

    case = DetailCaseSerializer()
    round = DetailRoundSerializer()
    sections = SectionSerializer(many=True)
    bundle = BundleItemSerializer(many=True)
    oaths = serializers.ListField(
        child=serializers.DictField(), required=False, help_text="Only where an oath is required."
    )
    checklist = serializers.ListField(child=serializers.CharField())
    alerts = AlertSerializer(many=True)
    courtrooms = NamedSerializer(many=True)
    registration_types = RegistrationTypeSerializer(many=True)
    flags = DetailFlagsSerializer()
    allowed_actions = serializers.ListField(child=serializers.CharField())
    workflow_version = serializers.IntegerField()


# Responses: history (#7.5)


class HistoryItemSerializer(serializers.Serializer):
    """One item of a send back and what became of it."""

    flag_id = serializers.UUIDField()
    label = serializers.CharField()
    what = serializers.JSONField(help_text="The note, or the value flagged.")
    state = serializers.CharField(help_text='"corrected 13 Jul", "resolved 3 Aug"')


class HistoryEntrySerializer(serializers.Serializer):
    """One line of the round timeline."""

    kind = serializers.CharField()
    at = serializers.DateTimeField()
    text = serializers.CharField()
    round = serializers.IntegerField(allow_null=True)
    stage = serializers.CharField(allow_null=True)
    items = HistoryItemSerializer(many=True, required=False)
    comment = serializers.CharField(required=False)


class HistorySerializer(serializers.Serializer):
    """GET /scrutiny/{case_id}/history/."""

    summary = serializers.CharField()
    entries = HistoryEntrySerializer(many=True)


class TitleResultSerializer(TitleSerializer):
    """The names now shown."""
