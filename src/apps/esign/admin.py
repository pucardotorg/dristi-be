"""eSign admin configuration.

Every field is read-only: a transaction's state is owned by the state machine,
and editing one by hand would break the guarantees the constraints enforce.
"""

from django.contrib import admin

from apps.core.mixins import AuditUserAdminMixin

from .models import ESignTransaction


@admin.register(ESignTransaction)
class ESignTransactionAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Read-only view of signing transactions for support and audit."""

    list_display = (
        "provider_transaction_id",
        "module",
        "entity_type",
        "entity_id",
        "status",
        "attempt_count",
        "signer",
        "created_at",
    )
    list_filter = ("status", "provider", "entity_type", "module")
    search_fields = (
        "id",
        "provider_transaction_id",
        "entity_id",
        "source_file_id",
        "placeholder_file_id",
        "signed_file_id",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("signer",)

    def get_readonly_fields(self, request, obj=None):
        """Show every concrete field read-only."""

        readonly = list(super().get_readonly_fields(request, obj))
        for field in self.model._meta.fields:
            if field.name not in readonly:
                readonly.append(field.name)
        return tuple(readonly)

    def has_add_permission(self, request):
        """Transactions are only created by the signing flow."""

        return False

    def has_change_permission(self, request, obj=None):
        """Transactions are never edited by hand."""

        return False
