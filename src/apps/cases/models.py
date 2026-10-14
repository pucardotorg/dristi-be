"""Case records, documents, cheque bounce details and evidence (spec 0020 §8-11)."""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseActivatableModel, BaseModel


class CaseType(models.TextChoices):
    """Dispute types; each one names its detail table."""

    CHEQUE_BOUNCE = "CHEQUE_BOUNCE", "Cheque bounce"


class CaseStatus(models.TextChoices):
    """E-filing lifecycle.

    Illustrative until statuses come from the case workflow configuration
    (spec 0020 §8.3, spec 0011).
    """

    DRAFT_IN_PROGRESS = "DRAFT_IN_PROGRESS", "Draft in progress"
    PENDING_SIGN = "PENDING_SIGN", "Pending sign"
    PENDING_PAYMENT = "PENDING_PAYMENT", "Pending payment"
    UNDER_SCRUTINY = "UNDER_SCRUTINY", "Under scrutiny"
    REGISTERED = "REGISTERED", "Registered"


# Cases in these statuses cannot be joined by case number (spec 0021 §2.1).
NOT_JOINABLE_STATUSES = (
    CaseStatus.DRAFT_IN_PROGRESS,
    CaseStatus.PENDING_SIGN,
    CaseStatus.PENDING_PAYMENT,
    CaseStatus.UNDER_SCRUTINY,
)


class Case(BaseModel):
    """One filing: only what every dispute type shares (spec 0020 §8).

    A case created from a draft session keeps the session id as its primary
    key, so the id the client already holds stays valid after the first save.
    """

    case_type = models.CharField(max_length=32, choices=CaseType.choices)
    filing_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    case_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    cnr_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=32, choices=CaseStatus.choices, default=CaseStatus.DRAFT_IN_PROGRESS
    )
    court_id = models.CharField(max_length=64, null=True, blank=True)
    filed_at = models.DateTimeField(null=True, blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        indexes = [
            models.Index(fields=["status", "created_by"]),
            models.Index(fields=["case_type", "status"]),
        ]

    def __str__(self):
        return self.case_number or self.filing_number or f"{self.case_type} draft {self.id}"


class DocumentType(models.TextChoices):
    """Case-level document types for cheque bounce cases (spec 0020 §9.3)."""

    BOUNCED_CHEQUE = "BOUNCED_CHEQUE", "Bounced cheque"
    RETURN_MEMO = "RETURN_MEMO", "Return memo"
    LEGAL_DEMAND_NOTICE = "LEGAL_DEMAND_NOTICE", "Legal demand notice"
    PROOF_OF_DISPATCH = "PROOF_OF_DISPATCH", "Proof of dispatch"
    PROOF_OF_DEBT = "PROOF_OF_DEBT", "Proof of debt"
    AFFIDAVIT = "AFFIDAVIT", "Affidavit"
    VAKALATNAMA = "VAKALATNAMA", "Vakalatnama"
    POA_DOCUMENT = "POA_DOCUMENT", "POA document"
    OTHER_SUPPORTING_DOCUMENT = "OTHER_SUPPORTING_DOCUMENT", "Other supporting document"


class CaseDocument(BaseModel, BaseActivatableModel):
    """A stored file filed as part of a case (spec 0020 §9).

    Removing a document from the case sets ``is_active = False``; the file
    itself is never deleted through here.
    """

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="documents")
    document = models.ForeignKey(
        "files.File", on_delete=models.PROTECT, related_name="case_documents"
    )
    document_type = models.CharField(max_length=64, choices=DocumentType.choices)
    additional_details = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(
                fields=["case", "document"], name="cases_case_document_unique_file"
            ),
        ]
        indexes = [models.Index(fields=["case", "document_type", "is_active"])]

    def __str__(self):
        return f"{self.document_type} for {self.case_id}"


class ChequeBounceCase(BaseModel):
    """Cheque bounce details, one row per case (spec 0020 §10).

    The case id is the primary key, which enforces the 1:1 relationship.
    Each JSON column holds one section of the filing form.
    """

    # Replaces BaseModel's own UUID key.
    id = None
    case = models.OneToOneField(
        Case,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="cheque_bounce",
        db_column="id",
    )
    jurisdiction_limitation = models.JSONField(default=dict, blank=True)
    adr_other_prayer = models.JSONField(default=dict, blank=True)
    additional_details = models.JSONField(default=dict, blank=True)

    # The sections PUT /cases/{id}/details/{section} may replace.
    SECTIONS = ("jurisdiction_limitation", "adr_other_prayer")

    def __str__(self):
        return f"Cheque bounce details for {self.case_id}"


class EvidenceType(models.TextChoices):
    """Evidence types with an ``evidence_info`` schema (spec 0021 §5.2)."""

    CHEQUE = "CHEQUE", "Cheque"
    RETURN_MEMO = "RETURN_MEMO", "Return memo"
    LEGAL_DEMAND_NOTICE = "LEGAL_DEMAND_NOTICE", "Legal demand notice"


class CaseEvidence(BaseModel, BaseActivatableModel):
    """A piece of evidence with type-specific details (spec 0020 §11).

    ``ordinal`` numbers the active evidence of one type within a case:
    cheque #1, cheque #2.
    """

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="evidence")
    case_document = models.ForeignKey(
        CaseDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evidence",
    )
    evidence_type = models.CharField(max_length=64, choices=EvidenceType.choices)
    ordinal = models.PositiveSmallIntegerField()
    evidence_info = models.JSONField(default=dict, blank=True)
    additional_details = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(
                fields=["case", "evidence_type", "ordinal"],
                condition=Q(is_active=True),
                name="cases_case_evidence_unique_active_ordinal",
            ),
        ]
        indexes = [models.Index(fields=["case", "evidence_type", "is_active"])]

    def __str__(self):
        return f"{self.evidence_type} #{self.ordinal} for {self.case_id}"
