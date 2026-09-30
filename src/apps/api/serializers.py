"""Shared API serializer base classes."""

from rest_framework import serializers

from apps.users.serializers import AuditUserSerializer, UserSerializer

AUDIT_FIELDS = ("created_by", "updated_by")


class AuditedModelSerializer(serializers.ModelSerializer):
    """Base serializer exposing the read-only audit users of ``BaseModel``.

    The nested representation is intentionally minimal (see
    :class:`apps.users.serializers.AuditUserSerializer`) because these two
    fields are attached to every audited resource.
    """

    created_by = AuditUserSerializer(read_only=True)
    updated_by = AuditUserSerializer(read_only=True)

    @staticmethod
    def with_audit_users(queryset):
        """Return ``queryset`` with the audit users joined in.

        Nesting the audit users costs two extra queries per row otherwise,
        which turns any list endpoint into an N+1.
        """
        return queryset.select_related(*AUDIT_FIELDS)


__all__ = ["AUDIT_FIELDS", "AuditedModelSerializer", "AuditUserSerializer", "UserSerializer"]
