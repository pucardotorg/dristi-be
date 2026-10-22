"""Cases admin configuration."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import (
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    ChequeBounceCase,
    PoaMandate,
)


@admin.register(Case)
class CaseAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for cases."""

    list_display = ("id", "case_type", "status", "filing_number", "case_number", "created_at")
    list_filter = ("case_type", "status")
    search_fields = ("id", "filing_number", "case_number", "cnr_number")
    raw_id_fields = ("court",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(CaseParticipant)
class CaseParticipantAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for case participants."""

    list_display = ("case", "role", "ordinal", "name_at_filing", "is_active", "created_at")
    list_filter = ("role", "is_active", "is_party_in_person", "has_signed")
    search_fields = ("case__id", "case__filing_number", "name_at_filing", "phone_number_at_filing")
    raw_id_fields = ("case", "person", "institution", "address")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(PoaMandate)
class PoaMandateAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Admin configuration for POA mandates."""

    list_display = (
        "case",
        "poa_participant",
        "represented_participant",
        "poa_type",
        "is_active",
        "granted_at",
        "revoked_at",
    )
    list_filter = ("is_active",)
    search_fields = (
        "case__id",
        "case__filing_number",
        "poa_participant__name_at_filing",
        "represented_participant__name_at_filing",
    )
    raw_id_fields = ("case", "poa_participant", "represented_participant")
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
