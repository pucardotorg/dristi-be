"""Admin configuration for the request workflow."""

from django.contrib import admin

from .models import (
    ApprovalStep,
    LawyerBarDocument,
    LawyerProfile,
    Request,
    RequestApproval,
    RequestDocument,
    RequestType,
)


class ApprovalStepInline(admin.TabularInline):
    """Inline editor for a request type's approval steps."""

    model = ApprovalStep
    extra = 1
    fields = ("order", "approver_role", "approver_group", "condition")


@admin.register(RequestType)
class RequestTypeAdmin(admin.ModelAdmin):
    """Admin configuration for request types."""

    list_display = ("code", "name", "min_documents", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [ApprovalStepInline]


@admin.register(ApprovalStep)
class ApprovalStepAdmin(admin.ModelAdmin):
    """Admin configuration for approval step templates."""

    list_display = ("request_type", "order", "approver_role", "approver_group")
    list_filter = ("request_type",)
    readonly_fields = ("id", "created_at", "updated_at")


class RequestDocumentInline(admin.TabularInline):
    """Inline listing of a request's documents."""

    model = RequestDocument
    extra = 0
    fields = ("file", "uploaded_by", "uploaded_at")
    readonly_fields = ("uploaded_at",)


class RequestApprovalInline(admin.TabularInline):
    """Inline listing of a request's approval trail."""

    model = RequestApproval
    extra = 0
    fields = ("version", "step_order", "approver", "status", "comments", "decided_at")
    readonly_fields = ("decided_at",)


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    """Admin configuration for requests."""

    list_display = (
        "id",
        "request_type",
        "requester",
        "status",
        "version",
        "current_step",
        "created_at",
    )
    list_filter = ("status", "request_type")
    search_fields = ("id", "requester__email")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [RequestDocumentInline, RequestApprovalInline]


@admin.register(RequestApproval)
class RequestApprovalAdmin(admin.ModelAdmin):
    """Admin configuration for approvals."""

    list_display = ("request", "version", "step_order", "approver", "status", "decided_at")
    list_filter = ("status",)
    search_fields = ("request__id", "approver__email")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(RequestDocument)
class RequestDocumentAdmin(admin.ModelAdmin):
    """Admin configuration for request documents."""

    list_display = ("id", "request", "file", "uploaded_by", "uploaded_at")
    search_fields = ("request__id",)
    readonly_fields = ("id", "created_at", "updated_at", "uploaded_at")


@admin.register(LawyerProfile)
class LawyerProfileAdmin(admin.ModelAdmin):
    """Admin configuration for lawyer profiles."""

    list_display = ("user", "name", "bar_number", "updated_at")
    search_fields = ("user__email", "name", "bar_number")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(LawyerBarDocument)
class LawyerBarDocumentAdmin(admin.ModelAdmin):
    """Admin configuration for lawyer bar documents."""

    list_display = ("person", "request_document", "created_at")
    search_fields = ("person__user__email",)
    readonly_fields = ("id", "created_at", "updated_at")
