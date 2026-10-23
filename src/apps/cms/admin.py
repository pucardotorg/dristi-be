"""CMS admin configuration."""

from django.contrib import admin

from apps.core.mixins import AuditUserAdminMixin

from .models import Page, PageCategory


@admin.register(Page)
class PageAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for CMS pages."""

    list_display = ("slug", "title", "content_type", "created_at", "updated_at")
    search_fields = ("slug", "title", "sub_title")
    list_filter = ("content_type", "categories")
    filter_horizontal = ("categories",)
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("title", "slug")


@admin.register(PageCategory)
class PageCategoryAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for page categories."""

    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)
