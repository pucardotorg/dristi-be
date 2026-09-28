"""Admin registration for accounts and profiles."""

from django.contrib import admin

from .models import AdvocateProfile, ClerkProfile, LitigantProfile, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Accounts, browsable by registration state."""

    list_display = (
        "mobile_number",
        "name",
        "role",
        "registration_status",
        "is_staff",
        "created_at",
    )
    list_filter = ("registration_status", "role", "is_staff", "is_active")
    search_fields = ("mobile_number", "name", "email")
    ordering = ("-created_at",)

    # Server-set values, including the acceptance evidence: editable evidence is
    # not evidence.
    readonly_fields = (
        "id",
        "password",
        "last_login",
        "created_at",
        "updated_at",
        "terms_accepted_at",
        "terms_version_accepted",
    )

    fieldsets = (
        (None, {"fields": ("id", "mobile_number", "name", "email", "role")}),
        ("Registration", {"fields": ("registration_status",)}),
        ("Terms", {"fields": ("terms_accepted_at", "terms_version_accepted")}),
        # Groups and per-object permissions are deliberately not editable here.
        ("Access", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
        ("Credentials", {"fields": ("password",)}),
    )


@admin.register(LitigantProfile)
class LitigantProfileAdmin(admin.ModelAdmin):
    """Litigant profiles."""

    list_display = ("name", "user", "created_at")
    search_fields = ("name", "user__mobile_number", "user__name")
    list_select_related = ("user",)


@admin.register(AdvocateProfile)
class AdvocateProfileAdmin(admin.ModelAdmin):
    """Advocate profiles. The registration id is an unverified claim."""

    list_display = (
        "bar_registration_id",
        "name",
        "user",
        "advocate_type",
        "approval_status",
        "created_at",
    )
    list_filter = ("approval_status", "advocate_type")
    search_fields = ("bar_registration_id", "name", "user__mobile_number", "user__name")
    list_select_related = ("user",)


@admin.register(ClerkProfile)
class ClerkProfileAdmin(admin.ModelAdmin):
    """Clerk profiles. The registration number is an unverified claim."""

    list_display = ("clerk_registration_number", "name", "user", "approval_status", "created_at")
    list_filter = ("approval_status",)
    search_fields = ("clerk_registration_number", "name", "user__mobile_number", "user__name")
    list_select_related = ("user",)
