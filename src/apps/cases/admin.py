"""Cases admin configuration."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import Case, CaseDocument, CaseEvidence, ChequeBounceCase


@admin.register(Case)
class CaseAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for cases."""

    list_display = ("id", "case_type", "status", "filing_number", "case_number", "created_at")
    list_filter = ("case_type", "status")
    search_fields = ("id", "filing_number", "case_number", "cnr_number")
    raw_id_fields = ("court",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CaseDocument)
class CaseDocumentAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for case documents."""

    list_display = ("case", "document_type", "is_active", "created_at")
    list_filter = ("document_type", "is_active")
    raw_id_fields = ("case", "document")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ChequeBounceCase)
class ChequeBounceCaseAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for cheque bounce details."""

    list_display = ("case", "updated_at")
    raw_id_fields = ("case",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(CaseEvidence)
class CaseEvidenceAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for case evidence."""

    list_display = ("case", "evidence_type", "ordinal", "is_active", "created_at")
    list_filter = ("evidence_type", "is_active")
    raw_id_fields = ("case", "case_document")
    readonly_fields = ("id", "created_at", "updated_at")
