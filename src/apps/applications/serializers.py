"""Request and response serializers (spec 0033 #15.5).

Serializers check shape only: UUIDs, enum values, dates, lengths. ``data`` is
checked against the type's schema, and sides, circles, signers, statuses,
availability and completeness in the services under the application lock.
Response serializers document the selectors' payloads for Swagger.
"""

from rest_framework import serializers

from apps.esign.serializers import SignPlaceholderSerializer

from .enums import ApplicationStatus, Side, SigningMethod
from .models import ApplicationDocument, ApplicationType

# Requests -----------------------------------------------------------------------------


class ApplicationWriteSerializer(serializers.Serializer):
    """``PATCH`` fields; ``POST`` adds the type (#6.3). Read-only fields are ignored."""

    raised_by = serializers.UUIDField(required=False, allow_null=True)
    litigant = serializers.UUIDField(required=False, allow_null=True)
    details = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    data = serializers.DictField(required=False)


class ApplicationCreateSerializer(ApplicationWriteSerializer):
    application_type = serializers.CharField(max_length=32)
    objection_to = serializers.UUIDField(required=False, allow_null=True)


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    field_path = serializers.CharField(max_length=128, required=False, allow_blank=True)


class SignSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=SigningMethod.choices)
    sign_placeholder = SignPlaceholderSerializer(required=False)


class SignConfirmSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()


class SignUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class CaseListQuerySerializer(serializers.Serializer):
    type = serializers.CharField(required=False, max_length=32)
    status = serializers.ChoiceField(choices=ApplicationStatus.choices, required=False)
    filed_by = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, max_length=100)
    pending = serializers.BooleanField(required=False, default=False)
    ordering = serializers.ChoiceField(
        choices=["-created_at", "created_at", "submitted_at", "-submitted_at"],
        required=False,
    )


class CourtQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()


class CourtQueueQuerySerializer(CourtQuerySerializer):
    view = serializers.ChoiceField(
        choices=["all", "onboard", "decide", "signing", "upcoming", "closed", "archive"],
        required=False,
    )
    queue = serializers.ChoiceField(
        choices=["rescheduling", "delay_condonation", "other"], required=False
    )
    type = serializers.CharField(required=False, max_length=32)
    side = serializers.ChoiceField(choices=Side.choices, required=False)
    stage = serializers.CharField(required=False, max_length=64)
    search = serializers.CharField(required=False, max_length=100)
    ordering = serializers.ChoiceField(
        choices=["due_date", "submitted_at", "-submitted_at", "next_hearing", "-delay_days"],
        required=False,
    )


class CourtListQuerySerializer(CourtQuerySerializer):
    status = serializers.ChoiceField(choices=ApplicationStatus.choices, required=False)
    type = serializers.CharField(required=False, max_length=32)
    decision_date_before = serializers.DateField(required=False)


# Responses ----------------------------------------------------------------------------


class TypeRefSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()


class ApplicationTypeSerializer(serializers.ModelSerializer):
    """One offered type (#6.1, #6.2)."""

    suggested = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = ApplicationType
        fields = ["code", "label", "description", "template_code", "suggested"]
        read_only_fields = fields


class ApplicationTypesSerializer(serializers.Serializer):
    can_raise = serializers.BooleanField()
    types = ApplicationTypeSerializer(many=True)


class LitigantOptionSerializer(serializers.Serializer):
    participant_id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField()


class RaisedByOptionSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.CharField()
    litigants = LitigantOptionSerializer(many=True)


class FormDefaultsSerializer(serializers.Serializer):
    raised_by = serializers.UUIDField(allow_null=True)
    litigant = serializers.UUIDField(allow_null=True)


class FormContextSerializer(serializers.Serializer):
    type = ApplicationTypeSerializer()
    raised_by_options = RaisedByOptionSerializer(many=True)
    defaults = FormDefaultsSerializer()
    system_fields = serializers.DictField()


class DocumentSerializer(serializers.ModelSerializer):
    is_supporting = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApplicationDocument
        fields = ["id", "is_supporting", "field_path", "name", "file_id", "sequence"]
        read_only_fields = fields


class ApplicationRowSerializer(serializers.Serializer):
    """A row of the case's applications (#14.1)."""

    id = serializers.UUIDField()
    type = TypeRefSerializer()
    application_number = serializers.CharField(allow_null=True)
    earlier_application_number = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    status_label = serializers.CharField()
    side = serializers.CharField()
    filed_by = serializers.CharField(allow_null=True)
    filed_by_id = serializers.UUIDField(allow_null=True)
    drafted_by = serializers.CharField(allow_null=True)
    litigant = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    review_due_date = serializers.DateField(allow_null=True)
    decision_date = serializers.DateField(allow_null=True)
    respond_by = serializers.DateField(allow_null=True)
    has_objection = serializers.BooleanField()
    deciding_order = serializers.DictField(allow_null=True)
    outcome = serializers.CharField(allow_null=True)
    waiting_on = serializers.CharField(allow_null=True)
    actions = serializers.ListField(child=serializers.CharField())


class FilerSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    name = serializers.CharField(allow_null=True)
    side = serializers.CharField()


class NeedsAttentionGroupSerializer(serializers.Serializer):
    step = serializers.CharField()
    action_label = serializers.CharField()
    filed_by = serializers.CharField(required=False, allow_null=True)
    application_ids = serializers.ListField(child=serializers.UUIDField())
    demand_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    lines = serializers.ListField(child=serializers.DictField(), required=False)
    total = serializers.CharField(required=False)
    bulk_signing_available = serializers.BooleanField(required=False)
    type = serializers.CharField(required=False)
    application_number = serializers.CharField(required=False, allow_null=True)
    respond_by = serializers.DateField(required=False, allow_null=True)
    decision_date = serializers.DateField(required=False, allow_null=True)


class NeedsAttentionSerializer(serializers.Serializer):
    groups = NeedsAttentionGroupSerializer(many=True)


class ApplicationDetailSerializer(serializers.Serializer):
    """``GET /applications/{id}/`` (#14.3); court readers get the #14.4 keys too.

    The body is the selector's dict, passed through; this declares its shape.
    """

    id = serializers.UUIDField()
    case = serializers.DictField()
    type = serializers.DictField()
    status = serializers.CharField()
    status_label = serializers.CharField()
    side = serializers.CharField()
    application_number = serializers.CharField(allow_null=True)
    earlier_application_number = serializers.CharField(allow_null=True)
    raised_by = serializers.DictField(allow_null=True)
    litigant = serializers.DictField(allow_null=True)
    details = serializers.CharField()
    data = serializers.DictField()
    hearing = serializers.DictField(allow_null=True)
    documents = serializers.ListField(child=serializers.DictField())
    signed_file_id = serializers.CharField(allow_null=True)
    signed_at = serializers.DateTimeField(allow_null=True)
    signing_methods = serializers.ListField(child=serializers.CharField())
    fee = serializers.CharField()
    demand_id = serializers.UUIDField(allow_null=True)
    additional_attributes = serializers.DictField()
    created_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    filed_on = serializers.DateTimeField(allow_null=True)
    onboarded_at = serializers.DateTimeField(allow_null=True)
    review_due_date = serializers.DateField(allow_null=True)
    decision_date = serializers.DateField(allow_null=True)
    objections_invited = serializers.BooleanField(allow_null=True)
    respond_by = serializers.DateField(allow_null=True)
    outcome = serializers.CharField(allow_null=True)
    objection_status = serializers.CharField(allow_null=True)
    objection = serializers.DictField(allow_null=True)
    objection_to = serializers.DictField(allow_null=True)
    filed_after_deadline = serializers.BooleanField()
    deciding_order = serializers.DictField(allow_null=True)
    orders = serializers.ListField(child=serializers.DictField())
    previous_order = serializers.DictField(allow_null=True)
    workflow_status = serializers.CharField()
    workflow_summary = serializers.CharField(allow_null=True)
    review_deferred = serializers.BooleanField()
    review_deferral_count = serializers.IntegerField()
    history = serializers.ListField(child=serializers.DictField())
    drafted_by = serializers.CharField(allow_null=True)
    waiting_on = serializers.CharField(allow_null=True)
    step = serializers.CharField(allow_null=True)
    objection_invite = serializers.DictField(allow_null=True)
    allowed_actions = serializers.ListField(child=serializers.CharField())
    version = serializers.IntegerField()
    # Court view (#14.4): present for courtroom staff only.
    suggested_date = serializers.DateField(required=False, allow_null=True)
    order_actions = serializers.ListField(child=serializers.CharField(), required=False)
    can_draft_order = serializers.BooleanField(required=False)
    decision_hint = serializers.CharField(required=False, allow_null=True)
    court = serializers.DictField(required=False)
    task = serializers.DictField(required=False, allow_null=True)
    document = serializers.DictField(required=False)
    pending_order = serializers.DictField(required=False, allow_null=True)

    def to_representation(self, instance):
        return instance


class PreviewSerializer(serializers.Serializer):
    """The structured render of #6.5a."""

    court = serializers.CharField()
    case_number = serializers.CharField()
    matter = serializers.CharField()
    title = serializers.CharField()
    filed_for = serializers.CharField()
    parties = serializers.ListField(child=serializers.ListField(child=serializers.DictField()))
    entries = serializers.ListField(child=serializers.DictField())
    details = serializers.CharField()
    signatory = serializers.DictField()
    dated = serializers.DateField()
    file_id = serializers.CharField(allow_null=True)

    def to_representation(self, instance):
        return {key: instance.get(key) for key in self.fields}


class ESignStartSerializer(serializers.Serializer):
    """The e-sign form, unchanged from ``apps.esign`` (0015 #6.1)."""

    transaction_id = serializers.UUIDField()
    provider_transaction_id = serializers.CharField()
    expires_at = serializers.DateTimeField()
    esign_url = serializers.CharField()
    form_method = serializers.CharField()
    form_fields = serializers.DictField()


class ProceedToSignSerializer(serializers.Serializer):
    """The detail after *Proceed to sign*, plus whom it waits for (#6.5c)."""

    waiting_on = serializers.CharField(allow_null=True)
    application = ApplicationDetailSerializer()


class QueueRowSerializer(serializers.Serializer):
    """A row of the court's Applications screen (#14.5)."""

    application_id = serializers.UUIDField()
    type = TypeRefSerializer()
    application_number = serializers.CharField(allow_null=True)
    earlier_application_number = serializers.CharField(allow_null=True)
    case = serializers.DictField()
    side = serializers.CharField()
    filed_by = serializers.CharField(allow_null=True)
    submitted_at = serializers.DateTimeField()
    band = serializers.CharField(allow_null=True)
    task = serializers.DictField(allow_null=True)
    status_line = serializers.DictField()
    pending_order = serializers.DictField(allow_null=True)
    outcome = serializers.CharField(allow_null=True)
    deciding_order = serializers.DictField(allow_null=True)
    hearing = serializers.DictField(required=False, allow_null=True)
    proposed_date = serializers.CharField(required=False, allow_null=True)

    def to_representation(self, instance):
        return instance


class QueueCountsSerializer(serializers.Serializer):
    today = serializers.DateField()
    views = serializers.DictField(child=serializers.IntegerField())
    queues = serializers.DictField(child=serializers.IntegerField())
    badge = serializers.IntegerField()
