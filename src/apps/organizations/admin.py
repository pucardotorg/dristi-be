"""Organizations admin registration."""

from django import forms
from django.contrib import admin

from .models import Organization


class OrganizationAdminForm(forms.ModelForm):
    """Admin form enforcing the jurisdiction requirement for active organizations."""

    class Meta:
        """Meta options."""

        model = Organization
        fields = "__all__"

    def clean(self):
        """Require at least one jurisdiction location for active organizations."""
        cleaned_data = super().clean()
        if cleaned_data.get("is_active") and not cleaned_data.get("jurisdictions"):
            raise forms.ValidationError(
                "Active organizations must have at least one jurisdiction location."
            )
        return cleaned_data


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin configuration for organizations."""

    form = OrganizationAdminForm
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
    filter_horizontal = ("jurisdictions",)
