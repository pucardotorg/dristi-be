"""PDF API serializers (spec 0016 #4)."""

from django.conf import settings
from rest_framework import serializers

from apps.organizations.models import Organization

from .models import PDFJob, PDFJobRecord, PDFJobStatus

_KEY_FIELD = {"max_length": 100}
_TENANT_FIELD = {"max_length": 64}


class _DataField(serializers.JSONField):
    """Request payload: a JSON object within ``PDF_MAX_REQUEST_DATA_BYTES``."""

    def to_internal_value(self, data):
        import json

        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            raise serializers.ValidationError("data must be a JSON object.")
        size = len(json.dumps(value, separators=(",", ":"), default=str).encode("utf-8"))
        if size > settings.PDF_MAX_REQUEST_DATA_BYTES:
            raise serializers.ValidationError(
                f"data exceeds the {settings.PDF_MAX_REQUEST_DATA_BYTES} byte limit."
            )
        return value


class PDFRenderRequestSerializer(serializers.Serializer):
    """Body of ``POST /pdf/render/``."""

    key = serializers.CharField(**_KEY_FIELD)
    tenant_id = serializers.CharField(**_TENANT_FIELD)
    locale = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    data = _DataField()


class PDFJobCreateSerializer(PDFRenderRequestSerializer):
    """Body of ``POST /pdf/jobs/``."""

    entity_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    organization_id = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False, allow_null=True, default=None
    )
    force_regenerate = serializers.BooleanField(required=False, default=False)


class PDFJobRecordSerializer(serializers.ModelSerializer):
    """One bulk chunk of a job."""

    class Meta:
        """Meta options."""

        model = PDFJobRecord
        fields = ["sequence", "status", "count", "file_id", "error_code", "error_message"]
        read_only_fields = fields


class PDFJobSerializer(serializers.ModelSerializer):
    """Job representation returned by every job endpoint."""

    template_version = serializers.IntegerField(source="template_version.version", read_only=True)
    organization_id = serializers.UUIDField(read_only=True, allow_null=True)
    reused = serializers.SerializerMethodField()
    records = serializers.SerializerMethodField()

    class Meta:
        """Meta options."""

        model = PDFJob
        fields = [
            "id",
            "key",
            "template_version",
            "tenant_id",
            "entity_id",
            "organization_id",
            "status",
            "is_bulk",
            "file_ids",
            "total_count",
            "completed_count",
            "failed_count",
            "error_code",
            "error_message",
            "reused",
            "records",
            "queued_at",
            "started_at",
            "completed_at",
            "files_deleted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_reused(self, obj) -> bool:
        """Whether this response returned an existing job instead of creating one."""
        return bool(self.context.get("reused", False))

    def get_records(self, obj) -> list[dict]:
        """Bulk chunk statuses (detail responses only, to keep lists cheap)."""
        if not obj.is_bulk or not self.context.get("include_records"):
            return []
        return PDFJobRecordSerializer(obj.records.order_by("sequence"), many=True).data


class PDFJobFilterSerializer(serializers.Serializer):
    """Query parameters of ``GET /pdf/jobs/``."""

    entity_id = serializers.CharField(required=False, max_length=128)
    key = serializers.CharField(required=False, **_KEY_FIELD)
    tenant_id = serializers.CharField(required=False, **_TENANT_FIELD)
    status = serializers.ChoiceField(choices=PDFJobStatus.choices, required=False)


class PDFDownloadQuerySerializer(serializers.Serializer):
    """Query parameters of ``GET /pdf/jobs/{id}/download/``."""

    sequence = serializers.IntegerField(required=False, min_value=0)
    index = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        """``sequence`` (bulk chunk) and ``index`` (into file_ids) are exclusive."""
        if "sequence" in attrs and "index" in attrs:
            raise serializers.ValidationError("sequence and index are mutually exclusive.")
        return attrs
