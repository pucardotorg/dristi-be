"""Case filing serializers (spec 0021)."""

from rest_framework import serializers

from .models import Case, CaseDocument, CaseEvidence
from .services import services
from .services.case_types import CaseType, DocumentType, EvidenceType


class DraftSessionSerializer(serializers.Serializer):
    """A draft session: the request takes ``case_type``, the response adds the rest."""

    draft_session_id = serializers.UUIDField(read_only=True)
    case_type = serializers.ChoiceField(choices=CaseType.choices)
    created_at = serializers.DateTimeField(read_only=True)


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

    file = serializers.FileField()
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
