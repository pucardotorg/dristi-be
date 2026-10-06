"""Files admin configuration."""

from django.contrib import admin

from apps.core.mixins import AuditUserAdminMixin

from .models import File, FileTag


@admin.register(FileTag)
class FileTagAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for file tags."""

    list_display = ("name", "created_at")
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(File)
class FileAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for files.

    Files are created through the upload service, which stores the object in
    Object Storage before recording its metadata. A row added here would point
    at a storage key that does not exist, so adding is disabled; the
    storage-owned fields are read-only for the same reason.
    """

    list_display = (
        "file_name",
        "file_type",
        "organization",
        "user",
        "file_size",
        "is_active",
        "created_at",
    )
    list_filter = ("file_type", "is_active")
    search_fields = ("file_name", "storage_path", "user__email")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "storage_path",
        "content_type",
        "file_size",
    )
    list_select_related = ("organization", "user")
    filter_horizontal = ("tags",)

    def has_add_permission(self, request):
        """Disallow creating file metadata that has no stored object behind it."""
        return False
