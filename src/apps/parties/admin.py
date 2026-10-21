"""Parties admin configuration."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import Institution, Person


@admin.register(Institution)
class InstitutionAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for institutions."""

    list_display = ("entity_name", "entity_type", "contact_number", "email_address", "created_at")
    list_filter = ("entity_type",)
    search_fields = ("entity_name", "contact_number", "email_address")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("address",)


@admin.register(Person)
class PersonAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for people.

    Addresses are immutable, so they are picked by id rather than edited
    inline; a changed address is a new ``Address`` row.
    """

    list_display = (
        "name",
        "phone_number",
        "institution",
        "verification_level",
        "user",
        "created_at",
    )
    list_filter = ("verification_level", "gender")
    search_fields = ("name", "phone_number", "email_address", "relative_name")
    readonly_fields = ("id", "created_at", "updated_at")
    list_select_related = ("institution", "user")
    raw_id_fields = ("institution", "permanent_address", "correspondence_address", "user")
