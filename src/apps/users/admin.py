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
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
        ("Credentials", {"fields": ("password",)}),
    )


@admin.register(LitigantProfile)
class LitigantProfileAdmin(admin.ModelAdmin):
    """Litigant profiles."""

    list_display = ("user", "created_at")
    search_fields = ("user__mobile_number", "user__name")


@admin.register(AdvocateProfile)
class AdvocateProfileAdmin(admin.ModelAdmin):
    """Advocate profiles. The registration id is an unverified claim."""

    list_display = ("bar_registration_id", "user", "created_at")
    search_fields = ("bar_registration_id", "user__mobile_number", "user__name")


@admin.register(ClerkProfile)
class ClerkProfileAdmin(admin.ModelAdmin):
    """Clerk profiles. The registration number is an unverified claim."""

    list_display = ("clerk_registration_number", "user", "created_at")
    search_fields = ("clerk_registration_number", "user__mobile_number", "user__name")
