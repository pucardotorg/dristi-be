"""Orders API serializers (spec 0039 #11.5).

Request serializers check shape only: UUIDs, dates, enum values, HTML size, the
shortcut name pattern, duplicate-free id lists. Availability, combinations,
mandatory fields, lifecycle and roles are checked in the services under the
order lock. Response serializers render the dicts ``selectors`` build; the
fields the server owns (``status``, ``data_complete``, ``number``, every
``*_file_id``, versions, ``position``) are read only by never being accepted.
"""

import re

from rest_framework import serializers

from apps.api import errors as api_errors

from .enums import SHORTCUT_SCOPE_ORDER_TEXT, NextHearingState, SigningMethod

SHORTCUT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHORTCUT_SCOPES = (SHORTCUT_SCOPE_ORDER_TEXT,)


def _no_duplicates(values, message="Remove the repeated ids."):
    if len(values) != len({str(value) for value in values}):
        raise api_errors.INVALID.validation_error(message)
    return values


# -- Requests ------------------------------------------------------------------


class PresetSerializer(serializers.Serializer):
    """Items loaded in advance, outside a hearing (#5.2); not stored."""

    kind = serializers.ChoiceField(choices=["COGNIZANCE", "APPLICATION"])
    action = serializers.CharField(max_length=32, required=False, allow_blank=True)
    application_id = serializers.UUIDField(required=False)
    delay_application_id = serializers.UUIDField(required=False)
    onboarding = serializers.BooleanField(required=False, default=False)


class OrderCreateSerializer(serializers.Serializer):
    """``POST /orders/``: a hearing's draft, or a new draft on a case (#5.1, #5.2)."""

    hearing_id = serializers.UUIDField(required=False)
    case_id = serializers.UUIDField(required=False)
    preset = PresetSerializer(required=False)
    order_type = serializers.CharField(max_length=16, required=False)

    def validate(self, attrs):
        if bool(attrs.get("hearing_id")) == bool(attrs.get("case_id")):
            raise api_errors.INVALID.validation_error(
                {"hearing_id": ["Give either hearing_id or case_id."]}
            )
        if attrs.get("preset") and attrs.get("hearing_id"):
            raise api_errors.INVALID.validation_error(
                {"preset": ["A preset applies only to an order outside a hearing."]}
            )
        return attrs


class OrderTextSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class OrderTitleSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)


class OrderTypeSerializer(serializers.Serializer):
    order_type = serializers.CharField(max_length=16)
    remove_linked_documents = serializers.BooleanField(required=False, default=False)


class OrderDocumentSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()


class ItemCreateSerializer(serializers.Serializer):
    item_type = serializers.CharField(max_length=50)
    target_id = serializers.UUIDField(required=False, allow_null=True)
    values = serializers.DictField(required=False, default=dict)


class ItemValuesSerializer(serializers.Serializer):
    values = serializers.DictField()


class NextHearingInputSerializer(serializers.Serializer):
    """``PUT /orders/{id}/next-hearing/``: a date and a purpose, or not listed again (#6.4)."""

    state = serializers.ChoiceField(choices=NextHearingState.values[1:])
    date = serializers.DateField(required=False, allow_null=True)
    purpose = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )


class DiaryEntrySerializer(serializers.Serializer):
    same_as_text = serializers.BooleanField()
    text = serializers.CharField(required=False, allow_blank=True, default="")


class SignSerializer(serializers.Serializer):
    # Free text: the service answers a method this court cannot use with ``E14017``.
    method = serializers.CharField(
        max_length=32, required=False, default=SigningMethod.AADHAAR_ESIGN
    )


class SignConfirmSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()


class BulkItemSpecSerializer(serializers.Serializer):
    item_type = serializers.CharField(max_length=50)
    target_id = serializers.UUIDField(required=False, allow_null=True)
    values = serializers.DictField(required=False, default=dict)


class BulkItemsSerializer(serializers.Serializer):
    order_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    items = BulkItemSpecSerializer(many=True, allow_empty=False)

    def validate_order_ids(self, value):
        return _no_duplicates(value)


class BulkTextSerializer(serializers.Serializer):
    court = serializers.UUIDField()
    hearing_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    text = serializers.CharField(trim_whitespace=False)

    def validate_hearing_ids(self, value):
        return _no_duplicates(value)


class BulkNextHearingSerializer(NextHearingInputSerializer):
    court = serializers.UUIDField()
    hearing_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)

    def validate_hearing_ids(self, value):
        return _no_duplicates(value)


class PendingQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()
    tab = serializers.ChoiceField(
        choices=["drafting", "awaiting_signature", "order_data", "triggered"], required=False
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


class OrdersCourtQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()


class DiaryEntriesQuerySerializer(serializers.Serializer):
    court = serializers.UUIDField()
    date = serializers.DateField(required=False)
    state_type = serializers.CharField(required=False, max_length=16)


class CatalogueQuerySerializer(serializers.Serializer):
    order = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    category = serializers.CharField(required=False, allow_blank=True, max_length=32)


class ShortcutQuerySerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=SHORTCUT_SCOPES, required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=64)


class ShortcutSerializer(serializers.Serializer):
    """A shortcut: a name, its body and the screens it is offered on (``SHC-``)."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=64)
    body = serializers.CharField(trim_whitespace=False)
    scope = serializers.ListField(
        child=serializers.ChoiceField(choices=SHORTCUT_SCOPES), required=False, min_length=1
    )

    def validate_name(self, value):
        if not SHORTCUT_NAME_RE.fullmatch(value):
            raise api_errors.INVALID.validation_error(
                "Use lower case letters, digits and hyphens, starting with a letter or digit."
            )
        return value


# -- Responses -----------------------------------------------------------------


class OrderDetailSerializer(serializers.Serializer):
    """The order screen (#10.2); nested parts are rendered as the selector built them."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    stages = serializers.ListField(child=serializers.CharField())
    whose_move = serializers.CharField()
    type = serializers.DictField()
    title = serializers.CharField()
    case = serializers.DictField()
    hearing = serializers.DictField(allow_null=True)
    text = serializers.CharField(allow_blank=True)
    rendered_html = serializers.CharField()
    items = serializers.ListField(child=serializers.DictField())
    next_hearing = serializers.DictField()
    attendance_complete = serializers.BooleanField(allow_null=True)
    diary_entry = serializers.DictField()
    roznama = serializers.DictField(allow_null=True)
    linked_documents = serializers.ListField(child=serializers.DictField())
    data_complete = serializers.BooleanField()
    number = serializers.CharField(allow_blank=True)
    order_date = serializers.DateField(allow_null=True)
    signed_file_id = serializers.CharField(allow_blank=True)
    text_version = serializers.IntegerField()
    data_version = serializers.IntegerField()
    editing = serializers.DictField(allow_null=True)
    allowed_actions = serializers.ListField(child=serializers.CharField())


class NextHearingResultSerializer(OrderDetailSerializer):
    warnings = serializers.ListField(child=serializers.DictField(), required=False)


class PendingRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["ORDER", "ROZNAMA"])
    type = serializers.DictField(allow_null=True)
    title = serializers.CharField()
    case = serializers.DictField()
    hearing = serializers.DictField(allow_null=True)
    signature = serializers.ChoiceField(choices=["NOT_SENT", "AWAITING", "SIGNED"])
    order_data = serializers.ChoiceField(choices=["NOT_COMPLETE", "COMPLETE"])
    stages = serializers.ListField(child=serializers.CharField())
    my_action = serializers.CharField(allow_null=True)
    updated_at = serializers.DateTimeField()


class PendingCountsSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    badge = serializers.IntegerField(allow_null=True)


class ChangesSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True)
    rendered_html = serializers.CharField()
    text_version = serializers.IntegerField()
    data_version = serializers.IntegerField()
    items = serializers.ListField(child=serializers.DictField())
    next_hearing = serializers.DictField()
    editing = serializers.DictField(allow_null=True)


class SignInitiationSerializer(serializers.Serializer):
    transaction_id = serializers.CharField()
    provider_transaction_id = serializers.CharField(allow_blank=True)
    expires_at = serializers.DateTimeField()
    esign_url = serializers.CharField()
    form_method = serializers.CharField()
    form_fields = serializers.DictField(child=serializers.CharField())


class BulkResultSerializer(serializers.Serializer):
    done = serializers.ListField(child=serializers.UUIDField())
    skipped = serializers.ListField(child=serializers.DictField())
    warnings = serializers.ListField(child=serializers.DictField(), required=False)


class CatalogueItemSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    category = serializers.CharField(allow_blank=True)
    availability = serializers.CharField()
    target_type = serializers.CharField(allow_blank=True)
    field_schema = serializers.DictField()
    suggested = serializers.BooleanField()
    available = serializers.BooleanField()
    unavailable_reason = serializers.DictField(allow_null=True)


class OrderItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    position = serializers.IntegerField()
    item_type = serializers.DictField()
    target_id = serializers.UUIDField(allow_null=True)
    values = serializers.DictField()
    source = serializers.CharField()
    confirmed = serializers.BooleanField()
    unconfirmed_fields = serializers.ListField(child=serializers.CharField())
    problems = serializers.ListField(child=serializers.DictField())


class CaseOrderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.DictField()
    title = serializers.CharField()
    number = serializers.CharField(allow_blank=True)
    order_date = serializers.DateField(allow_null=True)
    status = serializers.CharField()
    business_of_the_day = serializers.CharField(allow_blank=True)
    signed_file_id = serializers.CharField(allow_blank=True)
    roznama_file_id = serializers.CharField(allow_blank=True)


class DiaryEntryRowSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    case = serializers.DictField()
    hearing_date = serializers.DateField(allow_null=True)
    hearing_purpose = serializers.CharField(allow_blank=True)
    entry = serializers.CharField(allow_blank=True)
    next_hearing = serializers.DictField()
    type = serializers.DictField()
    entry_label = serializers.CharField()
    roznama = serializers.DictField(allow_null=True)
