"""PDF admin: template authoring and read-only job inspection.

Template versions are authored here (open question 12). Saving runs model
``clean()``, so invalid ``format_config``/``data_config`` is rejected at
authoring time (#9). Jobs are created through the API only, so their admin is
read-only.
"""

from django.contrib import admin

from apps.core.mixins import AuditUserAdminMixin

from .models import PDFJob, PDFJobRecord, PDFTemplate, PDFTemplateVersion


class PDFTemplateVersionInline(admin.TabularInline):
    """Versions of a template, newest first (read-only summary)."""

    model = PDFTemplateVersion
    fields = ("version", "is_active", "created_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        """Versions are added from their own form, where both configs are edited."""
        return False


@admin.register(PDFTemplate)
class PDFTemplateAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for PDF templates."""

    list_display = ("key", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("key", "name")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [PDFTemplateVersionInline]


@admin.register(PDFTemplateVersion)
class PDFTemplateVersionAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for template versions.

    The version number is assigned on save. Saving a version with
    ``is_active`` set deactivates its siblings.
    """

    list_display = ("template", "version", "is_active", "created_at")
    list_filter = ("is_active", "template")
    search_fields = ("template__key",)
    readonly_fields = ("id", "version", "created_at", "updated_at")
    list_select_related = ("template",)


class PDFJobRecordInline(admin.TabularInline):
    """Bulk chunks of a job."""

    model = PDFJobRecord
    fields = ("sequence", "offset", "count", "status", "file_id", "attempt_count", "error_code")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """Chunks are planned by the worker."""
        return False


@admin.register(PDFJob)
class PDFJobAdmin(admin.ModelAdmin):
    """Read-only admin for generation jobs."""

    list_display = (
        "id",
        "key",
        "tenant_id",
        "entity_id",
        "status",
        "total_count",
        "completed_count",
        "failed_count",
        "created_at",
    )
    list_filter = ("status", "is_bulk", "key")
    search_fields = ("id", "key", "entity_id", "tenant_id", "reuse_key")
    list_select_related = ("template_version__template",)
    inlines = [PDFJobRecordInline]

    def get_readonly_fields(self, request, obj=None):
        """Every field is read-only."""
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        """Jobs are created through the API."""
        return False

    def has_change_permission(self, request, obj=None):
        """Jobs are never edited by hand."""
        return False
