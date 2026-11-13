"""Payments admin (spec 0017 #9.5, #10).

Everything is read-only: balances and statuses belong to the services, and
successful payments are frozen history. The only writes are operator actions,
each of which goes through ``PaymentService``.
"""

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from apps.api.errors import BusinessError

from . import selectors
from .enums import OPEN_PAYMENT_STATUSES, PaymentStatus
from .exceptions import PaymentNotConfirmable
from .models import Demand, DemandItem, Payment, PaymentAttestation, PaymentDemandItem
from .providers import registry
from .providers.base import ProviderError, ProviderNotConfigured
from .serializers import mask_phone
from .services import PaymentService

# Payment statuses a late collection may be recorded against (spec 0032 #8.5).
CLOSED_STATUSES = (PaymentStatus.FAILED, PaymentStatus.CANCELLED)


class ReadOnlyAdminMixin:
    """Show every concrete field read-only; no add, change or delete."""

    def get_readonly_fields(self, request, obj=None):
        """Every field."""

        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request, obj=None):
        """Rows are created only by the services."""

        return False

    def has_change_permission(self, request, obj=None):
        """Rows are never edited by hand (actions still run)."""

        return False

    def has_delete_permission(self, request, obj=None):
        """Money history is never deleted."""

        return False


class DemandItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    """The line items of a demand."""

    model = DemandItem
    extra = 0
    fields = (
        "position",
        "charge_type",
        "reference_type",
        "reference_id",
        "description",
        "quantity",
        "unit_amount",
        "amount",
        "paid_amount",
        "due_amount",
        "status",
    )
    ordering = ("position",)


@admin.register(Demand)
class DemandAdmin(ReadOnlyAdminMixin, SimpleHistoryAdmin):
    """Demands and their items."""

    list_display = (
        "demand_number",
        "case_id",
        "reference_type",
        "reference_id",
        "status",
        "total_amount",
        "paid_amount",
        "due_amount",
        "created_at",
    )
    list_filter = ("status", "reference_type", "currency")
    search_fields = ("demand_number", "=id", "=case__id", "reference_id")
    date_hierarchy = "created_at"
    inlines = (DemandItemInline,)


class AwaitingCollectionFilter(admin.SimpleListFilter):
    """``PENDING`` payments of providers completed by attestation (spec 0032 #10)."""

    title = "collection"
    parameter_name = "awaiting_collection"

    def lookups(self, request, model_admin):
        return [("yes", "Awaiting collection")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                status=PaymentStatus.PENDING, provider__in=registry.attested_names()
            )
        return queryset


class CollectionForm(forms.Form):
    """Record a collection: the common fields plus every method's detail fields.

    Detail fields are built from ``attestation_methods()``, so a new method
    needs no admin change. Business rules come from the service and provider.
    """

    amount = forms.DecimalField(max_digits=18, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField()
    receipt_number = forms.CharField(max_length=64)
    collected_at = forms.DateTimeField(
        help_text="When the money was handed over, in IST. Defaults to now.", required=False
    )
    remarks = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, methods=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.methods = list(methods)
        self.fields["method"].choices = [(m.code, m.label) for m in self.methods]
        self.detail_fields = {}
        for method in self.methods:
            for spec in method.fields:
                name = self.detail_name(method.code, spec.key)
                widget = forms.DateInput(attrs={"type": "date"}) if spec.kind == "date" else None
                self.fields[name] = forms.CharField(
                    label=f"{method.label}: {spec.label}",
                    max_length=spec.max_length,
                    required=False,  # required only for the chosen method, checked by the provider
                    widget=widget,
                )
                self.detail_fields[name] = (method.code, spec.key)

    @staticmethod
    def detail_name(method_code: str, key: str) -> str:
        return f"detail__{method_code}__{key}"

    def details(self) -> dict:
        """The detail values of the chosen method, keyed as the provider expects."""

        chosen = self.cleaned_data["method"]
        return {
            key: self.cleaned_data[name]
            for name, (code, key) in self.detail_fields.items()
            if code == chosen and self.cleaned_data.get(name)
        }

    def field_for(self, error_field: str | None) -> str | None:
        """The form field a service error's ``field`` belongs to, if any."""

        if not error_field:
            return None
        if error_field.startswith("details."):
            name = self.detail_name(self.cleaned_data.get("method", ""), error_field[8:])
            return name if name in self.fields else None
        return error_field if error_field in self.fields else None


class CancelCollectionForm(forms.Form):
    """The reason for cancelling an attested request on the payer's behalf."""

    reason = forms.CharField(max_length=255)


class PaymentDemandItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    """The demand items a payment pays."""

    model = PaymentDemandItem
    extra = 0
    fields = ("demand_item", "amount")


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdminMixin, SimpleHistoryAdmin):
    """Payments, with the operator actions for flagged and unconfirmed ones."""

    list_display = (
        "payment_number",
        "demand",
        "batch_id",
        "amount",
        "status",
        "provider",
        "provider_reference",
        "needs_reconciliation",
        "created_at",
    )
    list_filter = (
        AwaitingCollectionFilter,
        "status",
        "provider",
        "needs_reconciliation",
        "payment_mode",
    )
    search_fields = (
        "payment_number",
        "=id",
        "=batch_id",
        "provider_payment_id",
        "provider_reference",
        "demand__demand_number",
    )
    date_hierarchy = "created_at"
    list_select_related = ("demand",)
    inlines = (PaymentDemandItemInline,)
    actions = (
        "recheck_with_provider",
        "clear_reconciliation",
        "confirm_without_provider",
        "cancel_collection_request",
    )
    change_form_template = "admin/payments/payment/change_form.html"

    def get_search_results(self, request, queryset, search_term):
        """Also find an attested request by a reference typed in any form (spec 0032 #10)."""

        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        term = (search_term or "").strip()
        if not term:
            return queryset, may_have_duplicates
        references = []
        for name in registry.attested_names():
            try:
                references.append((name, registry.get(name).normalise_reference(term)))
            except (ProviderError, ProviderNotConfigured):
                continue
        for name, reference in references:
            queryset |= self.model.objects.filter(provider=name, provider_payment_id=reference)
        return queryset, may_have_duplicates or bool(references)

    # -- collection desk in the admin (spec 0032 #10) ------------------------
    def get_urls(self):
        prefix = f"{self.model._meta.app_label}_{self.model._meta.model_name}"
        custom = [
            path(
                "<uuid:object_id>/record-collection/",
                self.admin_site.admin_view(self.record_collection_view),
                name=f"{prefix}_record_collection",
            ),
            path(
                "<uuid:object_id>/record-late-collection/",
                self.admin_site.admin_view(self.record_late_collection_view),
                name=f"{prefix}_record_late_collection",
            ),
        ]
        return custom + super().get_urls()

    def collection_buttons(self, request, payment) -> list[tuple[str, str]]:
        """``(label, url)`` of the collection forms this user may open for ``payment``."""

        if payment is None or not registry.is_attested(payment.provider):
            return []
        prefix = f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}"
        if payment.status in OPEN_PAYMENT_STATUSES and request.user.has_perm(
            "payments.record_payment_collection"
        ):
            return [
                (
                    "Record collection",
                    reverse(f"{prefix}_record_collection", args=[payment.pk]),
                )
            ]
        if payment.status in CLOSED_STATUSES and request.user.has_perm(
            "payments.record_late_payment_collection"
        ):
            return [
                (
                    "Record late collection",
                    reverse(f"{prefix}_record_late_collection", args=[payment.pk]),
                )
            ]
        return []

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = dict(extra_context or {})
        payment = self.get_object(request, object_id)
        extra_context["collection_buttons"] = self.collection_buttons(request, payment)
        return super().change_view(request, object_id, form_url, extra_context)

    def record_collection_view(self, request, object_id):
        return self._collection_view(request, object_id, late=False)

    def record_late_collection_view(self, request, object_id):
        return self._collection_view(request, object_id, late=True)

    def _collection_view(self, request, object_id, *, late: bool):
        """Show the whole request and record its collection through ``PaymentService``.

        Times are entered and shown in IST, the court's time, whatever
        ``TIME_ZONE`` the server runs in.
        """

        with timezone.override(selectors.IST):
            return self._collection_view_in_court_time(request, object_id, late=late)

    def _collection_view_in_court_time(self, request, object_id, *, late: bool):
        payment = self.get_object(request, str(object_id))
        if payment is None or not registry.is_attested(payment.provider):
            raise Http404("No attested payment request matches the given id.")
        permission = (
            "payments.record_late_payment_collection"
            if late
            else "payments.record_payment_collection"
        )
        if not request.user.has_perm(permission):
            raise PermissionDenied
        allowed = CLOSED_STATUSES if late else OPEN_PAYMENT_STATUSES
        change_url = reverse("admin:payments_payment_change", args=[payment.pk])
        if payment.status not in allowed:
            self.message_user(
                request, "This payment request cannot be recorded now.", level=messages.ERROR
            )
            return HttpResponseRedirect(change_url)

        provider = registry.get(payment.provider)
        request_obj = selectors.collection_request(payment.provider, payment.provider_payment_id)
        form = CollectionForm(
            request.POST or None,
            methods=provider.attestation_methods(),
            initial={"amount": request_obj.amount, "collected_at": timezone.now()},
        )
        if request.method == "POST" and form.is_valid():
            try:
                PaymentService.record_collection(
                    provider=payment.provider,
                    provider_payment_id=payment.provider_payment_id,
                    amount=form.cleaned_data["amount"],
                    method=form.cleaned_data["method"],
                    receipt_number=form.cleaned_data["receipt_number"],
                    collected_at=form.cleaned_data["collected_at"],
                    details=form.details(),
                    remarks=form.cleaned_data["remarks"],
                    late=late,
                    actor=request.user,
                )
            except BusinessError as exc:
                field, message = _business_error(exc)
                form.add_error(form.field_for(field), message)
            else:
                self.message_user(request, "The collection was recorded.")
                return HttpResponseRedirect(change_url)

        first = request_obj.first
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Record late collection" if late else "Record collection",
            "original": payment,
            "request_obj": request_obj,
            "payer_name": first.payer.get("name") or "",
            "payer_phone": mask_phone(first.payer.get("phone")),
            "form": form,
            "late": late,
            "change_url": change_url,
        }
        return TemplateResponse(request, "admin/payments/payment/record_collection.html", context)

    def has_cancel_collection_permission(self, request):
        return request.user.has_perm("payments.cancel_payment_collection")

    @admin.action(
        description="Cancel collection request (enter a reason)",
        permissions=["cancel_collection"],
    )
    def cancel_collection_request(self, request, queryset):
        """Cancel open attested requests on the payer's behalf (spec 0032 #4.5)."""

        selected = queryset.filter(
            provider__in=registry.attested_names(), status__in=OPEN_PAYMENT_STATUSES
        )
        form = CancelCollectionForm(request.POST if "apply" in request.POST else None)
        if form.is_bound and form.is_valid():
            done = set()
            for payment in selected:
                key = (payment.provider, payment.provider_payment_id)
                if key in done:
                    continue
                done.add(key)
                try:
                    PaymentService.cancel_collection(
                        provider=payment.provider,
                        provider_payment_id=payment.provider_payment_id,
                        reason=form.cleaned_data["reason"],
                        actor=request.user,
                    )
                except BusinessError as exc:
                    self.message_user(
                        request,
                        f"{payment.payment_number}: {_business_error(exc)[1]}",
                        level=messages.WARNING,
                    )
            self.message_user(request, f"Cancelled {len(done)} collection request(s).")
            return None
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Cancel collection requests",
            "payments": selected,
            "form": form,
            "action": "cancel_collection_request",
            "selected": request.POST.getlist(admin.helpers.ACTION_CHECKBOX_NAME),
        }
        return TemplateResponse(request, "admin/payments/payment/cancel_collection.html", context)

    # Each operator action has its own permission (``Payment.Meta.permissions``).
    # ``permissions=["change"]`` cannot be used: change is always refused here.
    def has_recheck_status_permission(self, request):
        return request.user.has_perm("payments.recheck_payment_status")

    def has_resolve_reconciliation_permission(self, request):
        return request.user.has_perm("payments.resolve_payment_reconciliation")

    def has_confirm_manually_permission(self, request):
        return request.user.has_perm("payments.confirm_payment_manually")

    @admin.action(
        description="Re-check status with the payment's provider",
        permissions=["recheck_status"],
    )
    def recheck_with_provider(self, request, queryset):
        """Fetch and apply the provider's current verdict."""

        for payment in queryset.exclude(provider="").exclude(provider_payment_id=""):
            try:
                PaymentService.refresh_from_provider(payment)
            except (ProviderError, ProviderNotConfigured) as exc:
                self.message_user(
                    request, f"{payment.payment_number}: {exc}", level=messages.WARNING
                )
        self.message_user(request, "Re-checked the selected payments with their providers.")

    @admin.action(
        description="Mark reconciliation as resolved (credits nothing)",
        permissions=["resolve_reconciliation"],
    )
    def clear_reconciliation(self, request, queryset):
        """Clear the flag once an operator has dealt with the money outside the system."""

        for payment in queryset.filter(needs_reconciliation=True):
            PaymentService.clear_reconciliation(payment, actor=request.user, note="admin action")
        self.message_user(request, "Cleared the reconciliation flag on the selected payments.")

    @admin.action(
        description="Confirm payment collected outside a provider",
        permissions=["confirm_manually"],
    )
    def confirm_without_provider(self, request, queryset):
        """Credit an INITIATED payment no provider was engaged for (spec 0017 #9.3)."""

        for payment in queryset.filter(status=PaymentStatus.INITIATED, provider=""):
            try:
                PaymentService.confirm_payment(payment, actor=request.user)
            except PaymentNotConfirmable as exc:
                self.message_user(
                    request, f"{payment.payment_number}: {exc}", level=messages.WARNING
                )
        self.message_user(request, "Confirmed the selected provider-less payments.")


def _business_error(exc: BusinessError) -> tuple[str | None, str]:
    """``(field, message)`` of a ``BusinessError``'s detail."""

    detail = exc.detail
    if isinstance(detail, dict):
        field, messages_ = next(iter(detail.items()))
        message = messages_[0] if isinstance(messages_, list) else messages_
        return str(field), str(message)
    return None, str(detail)


@admin.register(PaymentAttestation)
class PaymentAttestationAdmin(ReadOnlyAdminMixin, SimpleHistoryAdmin):
    """Recorded collections: permanent, read-only (spec 0032 #10)."""

    list_display = (
        "receipt_number",
        "provider",
        "provider_payment_id",
        "amount",
        "method",
        "collected_at",
        "outcome",
        "created_by",
        "created_at",
    )
    list_filter = ("provider", "method", "outcome", "created_by")
    search_fields = ("receipt_number", "provider_payment_id")
    date_hierarchy = "collected_at"
    list_select_related = ("created_by",)
