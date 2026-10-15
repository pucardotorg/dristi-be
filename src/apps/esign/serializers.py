"""Request and response serializers for the eSign APIs (spec 0015 #6)."""

from rest_framework import serializers

from .clients import get_file_client
from .constants import PDF_CONTENT_TYPE, EntityType
from .exceptions import ESignError, ESignNotAPDF, ESignSourceNotFound
from .models import ESignTransaction


class SignPlaceholderSerializer(serializers.Serializer):
    """Where the signature goes on the page (spec 0015 #6.1, spec 0016 #14.1).

    Coordinates are PDF points from the bottom-left of the page. Whether they
    actually fit the document is decided by the PDF Service, which is the only
    component that has the bytes.
    """

    page = serializers.IntegerField(required=False, default=1)
    position = serializers.CharField(required=False, allow_blank=True, max_length=32)
    x = serializers.FloatField(min_value=0)
    y = serializers.FloatField(min_value=0)
    width = serializers.FloatField(min_value=1)
    height = serializers.FloatField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
    location = serializers.CharField(required=False, allow_blank=True, max_length=255)
    signer_name = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def to_internal_value(self, data):
        """Reject unknown placement keys instead of silently dropping them."""

        if isinstance(data, dict):
            unknown = sorted(set(data) - set(self.fields))
            if unknown:
                raise serializers.ValidationError(
                    {"sign_placeholder": f"Unknown key(s): {', '.join(unknown)}."}
                )
        return super().to_internal_value(data)

    def validate_page(self, value):
        """Reject page 0; negative values address pages from the end."""

        if value == 0:
            raise serializers.ValidationError("Page numbering starts at 1.")
        return value


class ESignInitiateSerializer(serializers.Serializer):
    """Payload of ``POST /esign/_esign``."""

    organization_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    module = serializers.CharField(max_length=64)
    entity_type = serializers.ChoiceField(
        choices=EntityType.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    entity_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    file_id = serializers.CharField(max_length=64)
    sign_placeholder = SignPlaceholderSerializer()

    def validate_file_id(self, value):
        """Resolve the source document and confirm it is a PDF."""

        try:
            metadata = get_file_client().get_metadata(value)
        except ESignSourceNotFound as exc:
            raise serializers.ValidationError(exc.message) from exc
        except ESignError as exc:
            raise serializers.ValidationError(exc.message) from exc

        content_type = (metadata.get("content_type") or "").split(";")[0].strip().lower()
        if content_type != PDF_CONTENT_TYPE:
            raise serializers.ValidationError(ESignNotAPDF.default_message)
        return value


class ESignInitiationResponseSerializer(serializers.Serializer):
    """Body returned by initiation and retry (spec 0015 #6.1).

    ``form_fields`` is opaque to the client: it is posted verbatim to
    ``esign_url`` so no provider knowledge leaks into the UI.
    """

    transaction_id = serializers.UUIDField()
    provider_transaction_id = serializers.CharField()
    expires_at = serializers.DateTimeField()
    esign_url = serializers.URLField()
    form_method = serializers.CharField()
    form_fields = serializers.DictField(child=serializers.CharField())


class ESignTransactionSerializer(serializers.ModelSerializer):
    """Status of a signing transaction (spec 0015 #6.2)."""

    transaction_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = ESignTransaction
        fields = (
            "transaction_id",
            "organization_id",
            "module",
            "entity_type",
            "entity_id",
            "provider",
            "provider_transaction_id",
            "source_file_id",
            "signed_file_id",
            "status",
            "attempt_count",
            "retry_of",
            "failure_code",
            "failure_message",
            "expires_at",
            "callback_received_at",
            "completed_at",
            "created_at",
        )
        read_only_fields = fields


class ESignErrorSerializer(serializers.Serializer):
    """Error body shape used by the eSign endpoints."""

    code = serializers.CharField()
    detail = serializers.CharField()
