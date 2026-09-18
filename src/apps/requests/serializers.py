"""Serializers for the generic request and approval workflow."""

import json

from django.urls import reverse
from rest_framework import serializers

from apps.users.models import User

from . import services
from .models import (
    ApprovalStep,
    Request,
    RequestApproval,
    RequestDocument,
    RequestType,
)
from .schema import SchemaValidationError, validate_against_schema


class ApprovalStepSerializer(serializers.ModelSerializer):
    """Read-only serializer for approval step templates."""

    approver_group = serializers.SlugRelatedField(slug_field="name", read_only=True)

    class Meta:
        """Meta options."""

        model = ApprovalStep
        fields = ["id", "order", "approver_role", "approver_group", "condition"]


class RequestTypeSerializer(serializers.ModelSerializer):
    """Serializer used for dynamic form rendering on the client."""

    approval_steps = ApprovalStepSerializer(many=True, read_only=True)

    class Meta:
        """Meta options."""

        model = RequestType
        fields = [
            "id",
            "code",
            "name",
            "description",
            "schema",
            "min_documents",
            "is_active",
            "approval_steps",
        ]


class ApproverSerializer(serializers.ModelSerializer):
    """Minimal representation of a user acting as approver or requester."""

    class Meta:
        """Meta options."""

        model = User
        fields = ["id", "email", "username"]


class RequestDocumentSerializer(serializers.ModelSerializer):
    """Serializer for request documents (metadata plus download URL)."""

    filename = serializers.CharField(read_only=True)
    download_url = serializers.SerializerMethodField()
    uploaded_by = ApproverSerializer(read_only=True)

    class Meta:
        """Meta options."""

        model = RequestDocument
        fields = ["id", "filename", "download_url", "uploaded_by", "uploaded_at"]

    def get_download_url(self, obj) -> str:
        """Return the authorization-checked download path for the document."""
        url = reverse("request-document-download", args=[obj.request_id, obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class RequestApprovalSerializer(serializers.ModelSerializer):
    """Serializer for a single approval entry in a request's trail."""

    approver = ApproverSerializer(read_only=True)

    class Meta:
        """Meta options."""

        model = RequestApproval
        fields = [
            "id",
            "request",
            "step_order",
            "version",
            "approver",
            "status",
            "comments",
            "decided_at",
            "created_at",
        ]
        read_only_fields = fields


class RequestSerializer(serializers.ModelSerializer):
    """Serializer for reading requests."""

    request_type = serializers.SlugRelatedField(slug_field="code", read_only=True)
    requester = ApproverSerializer(read_only=True)
    documents = RequestDocumentSerializer(many=True, read_only=True)

    class Meta:
        """Meta options."""

        model = Request
        fields = [
            "id",
            "request_type",
            "requester",
            "data",
            "status",
            "version",
            "current_step",
            "documents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class RequestDetailSerializer(RequestSerializer):
    """Request serializer that also embeds the approval trail."""

    approvals = RequestApprovalSerializer(many=True, read_only=True)

    class Meta(RequestSerializer.Meta):
        """Meta options."""

        fields = [*RequestSerializer.Meta.fields, "approvals"]
        read_only_fields = fields


class RequestApprovalDetailSerializer(RequestApprovalSerializer):
    """Approval serializer with the nested request (data + documents)."""

    request = RequestSerializer(read_only=True)

    class Meta(RequestApprovalSerializer.Meta):
        """Meta options."""


class GenericRequestCreateSerializer(serializers.Serializer):
    """Generic multipart create serializer shared by every request type."""

    request_type = serializers.SlugRelatedField(
        slug_field="code",
        queryset=RequestType.objects.filter(is_active=True),
    )
    attributes = serializers.CharField()
    documents = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True,
    )

    def validate_attributes(self, value):
        """Parse the attributes JSON string into a dict."""
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise serializers.ValidationError("attributes must be a valid JSON object.") from None
        if not isinstance(parsed, dict):
            raise serializers.ValidationError("attributes must be a JSON object.")
        return parsed

    def validate(self, attrs):
        """Validate attributes against the type schema and check document count."""
        request_type = attrs["request_type"]

        try:
            validate_against_schema(request_type.schema, attrs["attributes"])
        except SchemaValidationError as exc:
            raise serializers.ValidationError({"attributes": exc.errors}) from None

        doc_count = len(attrs.get("documents", []))
        if doc_count < request_type.min_documents:
            raise serializers.ValidationError(
                {
                    "documents": (
                        f"{request_type.name} requires at least "
                        f"{request_type.min_documents} document(s), got {doc_count}."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        """Create and submit the request with its documents."""
        return services.create_request(
            request_type=validated_data["request_type"],
            requester=self.context["request"].user,
            data=validated_data["attributes"],
            files=validated_data.get("documents", []),
        )


class DecisionSerializer(serializers.Serializer):
    """Payload for POST /approvals/{id}/decide/."""

    decision = serializers.ChoiceField(
        choices=[
            RequestApproval.Status.APPROVED,
            RequestApproval.Status.REJECTED,
        ]
    )
    comments = serializers.CharField(required=False, allow_blank=True, default="")
