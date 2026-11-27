"""Applications admin (spec 0033 #16.9).

``ApplicationType`` is editable except its code. Applications, their
documents and transitions are read-only, with the actions *Retry type
workflow* and, until ``apps.orders`` exists (#1.2), *Record order on
application*, which takes an order number and the *Application action*
answers and runs the same service the order handler runs.
"""

import uuid

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .enums import OPEN_STATUSES, Outcome, WorkflowStatus
from .models import (
    Application,
    ApplicationCounter,
    ApplicationDocument,
    ApplicationTransition,
    ApplicationType,
    OfficeMembership,
)
from .services import actions
from .tasks import run_type_workflow


class ReadOnlyAdminMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApplicationType)
class ApplicationTypeAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    list_display = ("code", "label", "template_code", "sequence", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "label")
    ordering = ("sequence", "code")
    readonly_fields = ("id", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        return (*readonly, "code") if obj else readonly

    def has_delete_permission(self, request, obj=None):
        return False


class DocumentInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = ApplicationDocument
    fields = ("name", "field_path", "file_id", "sequence")
    readonly_fields = fields
    extra = 0


class TransitionInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = ApplicationTransition
    fk_name = "application"
    fields = ("created_at", "action", "from_status", "to_status", "actor", "order_id", "summary")
    readonly_fields = fields
    extra = 0
    ordering = ("created_at",)


class RecordOrderForm(forms.Form):
    """The *Application action* answers (#8.2) for an order passed outside the system."""

    order_number = forms.CharField(max_length=64, help_text="As printed on the signed order.")
    order_date = forms.DateField(help_text="The date of the signed order.")
    onboard = forms.BooleanField(required=False, initial=True, label="Onboard the application?")
    decides = forms.BooleanField(required=False, label="Does this order decide it?")
    outcome = forms.ChoiceField(choices=[("", "—"), *Outcome.choices], required=False)
    cis_outcome = forms.CharField(max_length=64, required=False)
    bring_back_on = forms.DateField(required=False, label="Date to bring it back")
    respond = forms.BooleanField(required=False, label="Does the other party need to respond?")
    respond_by = forms.DateField(required=False)
    moves_hearing = forms.BooleanField(
        required=False, label="The order also moved the application's hearing"
    )


@admin.register(Application)
class ApplicationAdmin(ReadOnlyAdminMixin, AuditUserAdminMixin, SimpleHistoryAdmin):
    list_display = (
        "application_number",
        "application_type",
        "status",
        "side",
        "case",
        "submitted_at",
        "workflow_status",
    )
    list_filter = ("status", "application_type", "workflow_status", "side")
    search_fields = ("application_number", "earlier_application_number", "case__case_number")
    readonly_fields = [field.name for field in Application._meta.fields]
    inlines = (DocumentInline, TransitionInline)
    actions = ("retry_type_workflow",)
    change_form_template = "admin/applications/application/change_form.html"

    @admin.action(description="Retry type workflow")
    def retry_type_workflow(self, request, queryset):
        # The admin is read-only (has_change_permission is False for everyone), so the
        # model permission is checked directly, as the record-order view does.
        if not request.user.has_perm("applications.change_application"):
            self.message_user(
                request, "You do not have permission to retry workflows.", messages.ERROR
            )
            return
        count = 0
        for application in queryset.filter(
            workflow_status__in=(WorkflowStatus.FAILED, WorkflowStatus.PENDING)
        ):
            run_type_workflow.send(str(application.pk))
            count += 1
        self.message_user(request, f"Queued {count} type workflow(s).")

    def get_urls(self):
        return [
            path(
                "<uuid:object_id>/record-order/",
                self.admin_site.admin_view(self.record_order_view),
                name="applications_application_record_order",
            ),
            *super().get_urls(),
        ]

    def record_order_view(self, request, object_id):
        """PLACEHOLDER (#1.2): record an order's *Application action* until orders exist."""
        if not request.user.has_perm("applications.change_application"):
            messages.error(request, "You do not have permission to record orders.")
            return redirect(reverse("admin:applications_application_change", args=[object_id]))
        application = Application.objects.select_related("application_type").get(pk=object_id)
        form = RecordOrderForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            values = {
                "onboard": data["onboard"],
                "decides": data["decides"],
                "outcome": data["outcome"] or None,
                "cis_outcome": data["cis_outcome"] or None,
                "bring_back_on": data["bring_back_on"].isoformat()
                if data["bring_back_on"]
                else None,
                "respond": data["respond"],
                "respond_by": data["respond_by"].isoformat() if data["respond_by"] else None,
            }
            order_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"order:{application.case_id}:{data['order_number']}"
            )
            result = actions.apply(
                application.pk,
                values,
                order_id=order_id,
                actor=request.user,
                order_date=data["order_date"],
                moves_hearing=data["moves_hearing"],
            )
            if result.status == "DONE":
                messages.success(request, "Order recorded on the application.")
                return redirect(reverse("admin:applications_application_change", args=[object_id]))
            messages.error(request, f"Not recorded: {result.error_code}.")
        return render(
            request,
            "admin/applications/application/record_order.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Record order on {application}",
                "application": application,
                "form": form,
                "open": application.status in OPEN_STATUSES,
                "opts": self.model._meta,
            },
        )


@admin.register(ApplicationTransition)
class ApplicationTransitionAdmin(ReadOnlyAdminMixin, AuditUserAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "application_ref", "action", "from_status", "to_status", "actor")
    list_filter = ("action",)
    search_fields = ("application_ref", "summary")


@admin.register(ApplicationCounter)
class ApplicationCounterAdmin(ReadOnlyAdminMixin, AuditUserAdminMixin, admin.ModelAdmin):
    list_display = ("kind", "scope_key", "year", "last_number")


@admin.register(OfficeMembership)
class OfficeMembershipAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """PLACEHOLDER (#1.2): who works in which advocate's office, until office access exists."""

    list_display = ("member", "advocate", "is_active", "updated_at")
    list_filter = ("is_active",)
    autocomplete_fields = ("member", "advocate")
    readonly_fields = ("id", "created_at", "updated_at")
