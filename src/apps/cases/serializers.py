"""Case filing serializers (spec 0021)."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.organizations.models import Organization

from .models import Case, CaseDocument, CaseEvidence
from .services import services
from .services.case_types import CaseType, DocumentType, EvidenceType


@extend_schema_field(OpenApiTypes.BINARY)
class UploadField(serializers.FileField):
    """A file upload.

    drf-spectacular documents a plain ``FileField`` as a URL string, so
    Swagger would show a text box; ``binary`` gives it a file picker.
    """


class DraftSessionSerializer(serializers.Serializer):
    """A draft session.

    The request takes ``case_type`` and, optionally, the ``court_id`` of the
    court (an Organization) to file in; the response adds the rest.
    """

    draft_session_id = serializers.UUIDField(read_only=True)
    case_type = serializers.ChoiceField(choices=CaseType.choices)
    court_id = serializers.UUIDField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)

    def validate_court_id(self, court_id):
        """Accept only an existing, active organization."""
        if court_id is not None and not Organization.objects.active().filter(pk=court_id).exists():
            raise serializers.ValidationError("No active court with this id.")
        return court_id


class CaseSerializer(serializers.ModelSerializer):
    """Case metadata, for listings and the join-by-number lookup."""

    case_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = Case
        fields = [
            "case_id",
            "case_type",
            "filing_number",
            "case_number",
            "cnr_number",
            "status",
            "court_id",
            "filed_at",
            "registered_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CaseDocumentUploadSerializer(serializers.Serializer):
    """Multipart body of POST /cases/{id}/documents.

    ``document_type`` must be a known type here; whether the case's type
    accepts it is checked by the service.
    """

    file = UploadField()
    document_type = serializers.ChoiceField(choices=DocumentType.choices)

    def validate_file(self, upload):
        """Accept PDFs and images only."""
        content_type = (upload.content_type or "").split(";")[0].strip().lower()
        if content_type not in services.CONTENT_TYPE_FILE_TYPES:
            allowed = ", ".join(sorted(services.CONTENT_TYPE_FILE_TYPES))
            raise serializers.ValidationError(f"Unsupported file type; allowed: {allowed}.")
        return upload


class CaseDocumentSerializer(serializers.ModelSerializer):
    """A case document with its file's metadata."""

    case_document_id = serializers.UUIDField(source="id", read_only=True)
    file_name = serializers.CharField(source="document.file_name", read_only=True)
    file_size = serializers.IntegerField(source="document.file_size", read_only=True)

    class Meta:
        """Meta options."""

        model = CaseDocument
        fields = [
            "case_id",
            "case_document_id",
            "document_id",
            "document_type",
            "file_name",
            "file_size",
            "created_at",
        ]
        read_only_fields = fields


class EvidenceCreateSerializer(serializers.Serializer):
    """Body of POST /cases/{id}/evidence.

    ``evidence_info`` is checked against the case type's schema by the service.
    """

    evidence_type = serializers.ChoiceField(choices=EvidenceType.choices)
    case_document_id = serializers.UUIDField(required=False, allow_null=True)
    evidence_info = serializers.DictField()


class EvidenceUpdateSerializer(serializers.Serializer):
    """Body of PATCH /cases/{id}/evidence/{evidence_id}: ``evidence_info`` only."""

    evidence_info = serializers.DictField()


class CaseEvidenceSerializer(serializers.ModelSerializer):
    """A piece of evidence."""

    case_evidence_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = CaseEvidence
        fields = [
            "case_evidence_id",
            "case_id",
            "case_document_id",
            "evidence_type",
            "ordinal",
            "evidence_info",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CodeLabelSerializer(serializers.Serializer):
    """A code with its display label."""

    code = serializers.CharField()
    label = serializers.CharField()


class SectionDescriptionSerializer(serializers.Serializer):
    """A details section and the JSON Schema its data is validated against."""

    code = serializers.CharField()
    schema = serializers.DictField()


class EvidenceTypeDescriptionSerializer(CodeLabelSerializer):
    """An evidence type and the JSON Schema its ``evidence_info`` is validated against."""

    schema = serializers.DictField()


class CaseTypeDescriptionSerializer(serializers.Serializer):
    """What one case type accepts, for clients to build their forms from."""

    case_type = serializers.CharField()
    label = serializers.CharField()
    sections = SectionDescriptionSerializer(many=True)
    document_types = CodeLabelSerializer(many=True)
    evidence_types = EvidenceTypeDescriptionSerializer(many=True)


class DetailsSectionSerializer(serializers.Serializer):
    """Response of PUT /cases/{id}/details/{section}: the section as saved."""

    case_id = serializers.UUIDField()
    section = serializers.CharField()
    data = serializers.DictField()
