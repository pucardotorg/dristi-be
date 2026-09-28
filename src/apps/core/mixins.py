"""Reusable view and admin mixins for models inheriting from BaseModel."""


class AuditUserMixin:
    """Populate ``created_by`` / ``updated_by`` from the request user.

    Intended for DRF generic views and viewsets whose model inherits from
    :class:`apps.core.models.BaseModel`. When no authenticated user is
    available (anonymous request, background job, management command), the
    audit fields are left as ``NULL``.
    """

    def get_audit_user(self):
        """Return the authenticated request user, or ``None``."""
        user = getattr(getattr(self, "request", None), "user", None)
        if user is None or not user.is_authenticated:
            return None
        return user

    def perform_create(self, serializer):
        """Stamp both audit fields with the current user on create."""
        user = self.get_audit_user()
        serializer.save(created_by=user, updated_by=user)

    def perform_update(self, serializer):
        """Stamp only ``updated_by`` with the current user on update."""
        serializer.save(updated_by=self.get_audit_user())


class AuditUserAdminMixin:
    """Populate ``created_by`` / ``updated_by`` from the logged-in admin user.

    The audit fields are server-controlled, so they are shown read-only in the
    admin instead of being editable form inputs.
    """

    audit_fields = ("created_by", "updated_by")

    def get_readonly_fields(self, request, obj=None):
        """Return the configured read-only fields plus the audit fields."""
        readonly = tuple(super().get_readonly_fields(request, obj))
        return readonly + tuple(f for f in self.audit_fields if f not in readonly)

    def save_model(self, request, obj, form, change):
        """Stamp the audit fields with the current admin user before saving."""
        user = request.user if request.user.is_authenticated else None
        if not change:
            obj.created_by = user
        obj.updated_by = user
        super().save_model(request, obj, form, change)
