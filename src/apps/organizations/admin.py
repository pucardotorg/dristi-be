"""Organizations admin registration."""

from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin configuration for organizations."""

    list_display = (
        "code",
        "name",
        "short_name",
        "organization_type",
        "parent",
        "is_active",
    )
    list_filter = ("organization_type", "is_active")
    search_fields = ("code", "name", "short_name")
    readonly_fields = ("id", "created_at", "updated_at")

    # TODO(0007-location): add filter_horizontal = ("jurisdictions",) once
    # that field exists on the model (see models.py TODO).
