"""API serializer compatibility imports."""

from rest_framework import serializers

from apps.users.serializers import UserSerializer


class AuditedModelSerializer(serializers.ModelSerializer):
    """Base serializer exposing the read-only audit users of ``BaseModel``."""

    created_by = UserSerializer(read_only=True)
    updated_by = UserSerializer(read_only=True)


__all__ = ["AuditedModelSerializer", "UserSerializer"]
