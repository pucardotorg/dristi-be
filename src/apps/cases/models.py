"""Cases, participants, witnesses, POA mandates, representations, documents, evidence (spec 0020)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import BaseActivatableModel, BaseAuditableModel, BaseModel
from apps.parties.models import MAX_AGE
from apps.users.models import ApprovalStatus

from .services.case_types import CaseType, DocumentType, EvidenceType, get_config, schema_errors


class CaseStatus(models.TextChoices):
    """E-filing lifecycle.

    Important: Illustrative until statuses come from the case workflow configuration
    (spec 0020 §8.3, spec 0011).
    """

    DRAFT_IN_PROGRESS = "DRAFT_IN_PROGRESS", "Draft in progress"
    PENDING_SIGN = "PENDING_SIGN", "Pending sign"
    PENDING_PAYMENT = "PENDING_PAYMENT", "Pending payment"
    UNDER_SCRUTINY = "UNDER_SCRUTINY", "Under scrutiny"
    REGISTERED = "REGISTERED", "Registered"


# Only cases in these statuses can be joined by case number (spec 0021 §2.1).
# An allow-list, because the lookup is open to every registered user: a status
# added later stays hidden until it is listed here.
JOINABLE_STATUSES = (CaseStatus.REGISTERED,)


class Case(BaseModel, BaseAuditableModel):
    """One filing: only what every dispute type shares (spec 0020 §8).

    A case created from a draft session keeps the session id as its primary
    key, so the id the client already holds stays valid after the first save.
    """

    # Replaces BaseModel's nullable SET_NULL field: ownership is checked only
    # through created_by, so the filer must always be set and cannot be deleted
    # out from under the case (spec 0020 §8). Users are deactivated, not deleted.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cases_case_created_by",
    )
    case_type = models.CharField(max_length=32, choices=CaseType.choices)
    # all the "number" fields are not final yet, may differ in future
    filing_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    case_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    cnr_number = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(
        max_length=32, choices=CaseStatus.choices, default=CaseStatus.DRAFT_IN_PROGRESS
    )
    # The court is an Organization; drafts may not have one yet.
    court = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cases",
    )
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


class ParticipantRole(models.TextChoices):
    """The role a participant plays in a case (spec 0020 §4.2)."""

    COMPLAINANT = "COMPLAINANT", "Complainant"
    ACCUSED = "ACCUSED", "Accused"
    WITNESS = "WITNESS", "Witness"
    POA_HOLDER = "POA_HOLDER", "POA holder"


# Only these roles may be an institution; witnesses and POA holders are individuals.
INSTITUTION_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.ACCUSED)

# The filing side signs the complaint; the accused and witnesses never do (spec 0021 §8).
SIGNING_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.POA_HOLDER)

# Only the filing side, and its advocates, may preview the filing. An accused or
# witness who claims the person record they were entered as must not (spec 0021 §9.6).
FILING_SIDE_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.POA_HOLDER)

# A person holding one of these roles on a case cannot hold the other there.
OPPOSING_ROLES = {
    ParticipantRole.COMPLAINANT: ParticipantRole.ACCUSED,
    ParticipantRole.ACCUSED: ParticipantRole.COMPLAINANT,
}

# Messages shared by the model rules and the request checks that run before them.
ADDRESS_REQUIRED_MESSAGE = "An address for service of notice is required for this role."
INSTITUTION_ROLE_MESSAGE = "Only a complainant or an accused may be an institution."
DESIGNATION_REQUIRED_MESSAGE = "Enter the designation of the person acting for the institution."
DESIGNATION_NOT_ALLOWED_MESSAGE = "Only for a person acting for an institution."
PARTY_ROLE_MESSAGE = "Must be a complainant or an accused."
SAME_CASE_MESSAGE = "Must be a participant of the same case."
ACTIVE_PARTICIPANT_MESSAGE = "Must be an active participant."
# The rest of the rules' messages, so the API can tell the rules apart (see
# ``services.participants.MODEL_RULE_CODES``). ``{…}`` parts vary per error.
ROLE_HELD_MESSAGE = "This {field} is already {article} {role} on this case."
BOTH_SIDES_MESSAGE = "{party} cannot be both a complainant and an accused on a case."
CALLS_ACTIVE_WITNESS_MESSAGE = "Cannot be removed while an active witness is called by them."
NOT_A_WITNESS_MESSAGE = "Must be a witness."
NOT_A_POA_HOLDER_MESSAGE = "Must be a POA holder."
WITNESS_CALLED_TWICE_MESSAGE = "This person is already a witness called by this party."
MANDATE_FOR_SELF_MESSAGE = "A person cannot hold a mandate for themselves."
PARTICIPANT_MANDATE_FOR_SELF_MESSAGE = "A participant cannot hold a mandate for themselves."
DUPLICATE_MANDATE_MESSAGE = "This holder already has an active mandate for this party."
DUPLICATE_REPRESENTATION_MESSAGE = "This advocate already represents this party."
ADVOCATE_NOT_APPROVED_MESSAGE = "Must be an approved advocate."
PARTY_IN_PERSON_MESSAGE = "A party appearing in person cannot be given an advocate."
PARTY_HAS_ADVOCATES_MESSAGE = "Remove this party's advocates first."
ADVOCATE_FOR_SELF_MESSAGE = "An advocate cannot represent themselves."
ADVOCATE_BOTH_SIDES_MESSAGE = "An advocate cannot represent both a complainant and an accused."

# The order each is listed in, by the API and the preview.
PARTICIPANT_ORDERING = ("role", "ordinal")
POA_MANDATE_ORDERING = (
    "poa_participant__ordinal",
    "represented_participant__role",
    "represented_participant__ordinal",
)
REPRESENTATION_ORDERING = ("case_participant__role", "case_participant__ordinal", "from_date")
EVIDENCE_ORDERING = ("evidence_type", "ordinal")


def _raise_broken_rules(rules):
    """Raise a ``ValidationError`` listing every rule in ``rules`` that does not hold.

    ``rules`` are ``(field, rule holds, message when it does not)``. Every
    broken rule is reported, not just the first one per field.
    """
    errors = {}
    for field, holds, message in rules:
        if not holds:
            errors.setdefault(field, []).append(message)
    if errors:
        raise ValidationError(errors)


class CaseParticipant(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """One person's or institution's involvement in one case, in one role (spec 0020 §4).

    The ``*_at_filing`` columns are the case's frozen copy of the party's
    details; the ``person`` row keeps current data and is never changed to
    correct a case record. ``ordinal`` numbers the active participants of one
    role within a case: complainant #1, accused #2. Removal is a soft delete
    (``is_active = False``, ``end_date`` set); a removed row keeps its ordinal.
    """

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="participants")
    # The individual party, or the person acting for an institution.
    person = models.ForeignKey(
        "parties.Person",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="case_participations",
    )
    institution = models.ForeignKey(
        "parties.Institution",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="case_participations",
    )
    role = models.CharField(max_length=32, choices=ParticipantRole.choices)
    ordinal = models.PositiveSmallIntegerField()
    # The person's name, or the institution's when there is no person.
    name_at_filing = models.CharField(max_length=256)
    # 20 wide so an institution's landline fits.
    phone_number_at_filing = models.CharField(max_length=20, null=True, blank=True)
    gender_at_filing = models.CharField(max_length=32, null=True, blank=True)
    age_at_filing = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(MAX_AGE)]
    )
    designation_at_filing = models.CharField(max_length=128, null=True, blank=True)
    # The address for service of notice.
    address = models.ForeignKey(
        "address.Address",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    additional_details = models.JSONField(default=dict, blank=True)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    is_party_in_person = models.BooleanField(default=False)
    has_signed = models.BooleanField(default=False)
    signature_document = models.ForeignKey(
        "files.File",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.CheckConstraint(
                check=Q(person__isnull=False) | Q(institution__isnull=False),
                name="cases_case_participant_person_or_institution",
            ),
            models.CheckConstraint(
                check=Q(institution__isnull=True) | Q(role__in=INSTITUTION_ROLES),
                name="cases_case_participant_institution_role",
            ),
            models.CheckConstraint(
                check=Q(person__isnull=True)
                | Q(institution__isnull=True)
                | Q(designation_at_filing__isnull=False),
                name="cases_case_participant_designation_required",
            ),
            models.CheckConstraint(
                check=Q(role__in=ParticipantRole.values),
                name="cases_case_participant_role_valid",
            ),
            models.UniqueConstraint(
                fields=["case", "role", "ordinal"],
                condition=Q(is_active=True),
                name="cases_case_participant_unique_active_ordinal",
            ),
        ]
        indexes = [models.Index(fields=["case", "role", "is_active"])]

    def __str__(self):
        return f"{self.role} #{self.ordinal} ({self.name_at_filing}) for {self.case_id}"

    def clean(self):
        """Apply the rules the database cannot express (spec 0020 §4.2, §14.1).

        Every role but a witness needs an address for service of notice. While
        active, a person or an institution cannot hold one role twice on a
        case, nor be both a complainant and an accused there, nor appear in
        person while an advocate actively represents them. A participant
        cannot be removed while an active witness names them as its caller.
        """
        super().clean()
        # Not a ``_raise_broken_rules`` list: the role-conflict and witness
        # checks query the database, and run only when the cheaper rules allow.
        errors = {}
        if self.role != ParticipantRole.WITNESS and not self.address_id:
            errors["address"] = ADDRESS_REQUIRED_MESSAGE
        if self.institution_id and self.role not in INSTITUTION_ROLES:
            errors["institution"] = INSTITUTION_ROLE_MESSAGE
        if self.person_id and self.institution_id and not self.designation_at_filing:
            errors["designation_at_filing"] = DESIGNATION_REQUIRED_MESSAGE
        for field in ("person", "institution"):
            if field not in errors and (message := self._role_conflict(field)):
                errors[field] = message
        if (
            not self.is_active
            and self.pk
            and Witness.objects.filter(
                called_by_participant_id=self.pk, case_participant__is_active=True
            ).exists()
        ):
            errors["is_active"] = CALLS_ACTIVE_WITNESS_MESSAGE
        if (
            self.is_active
            and self.is_party_in_person
            and self.pk
            and self.representations.active().exists()
        ):
            errors["is_party_in_person"] = PARTY_HAS_ADVOCATES_MESSAGE
        if errors:
            raise ValidationError(errors)

    def _role_conflict(self, field):
        """Return why the ``person`` or ``institution`` cannot take this role here, or ``None``.

        Only active participants count, so a party removed from a case can be
        added again. A person may be a witness more than once, since a witness
        recalled by the other side is a new participant; ``Witness.clean``
        refuses the same caller twice.
        """
        party_id = getattr(self, f"{field}_id")
        if not (self.is_active and self.case_id and party_id):
            return None
        held = set(
            CaseParticipant.objects.active()
            .filter(case_id=self.case_id, **{f"{field}_id": party_id})
            .exclude(pk=self.pk)
            .values_list("role", flat=True)
        )
        if self.role in held and self.role != ParticipantRole.WITNESS:
            role = self.get_role_display().lower()
            article = "an" if role[0] in "aeiou" else "a"
            return ROLE_HELD_MESSAGE.format(field=field, article=article, role=role)
        if OPPOSING_ROLES.get(self.role) in held:
            party = "An institution" if field == "institution" else "A person"
            return BOTH_SIDES_MESSAGE.format(party=party)
        return None


class Witness(BaseModel, BaseAuditableModel):
    """What only a witness has, one row per witness participant (spec 0020 §4.5).

    The participant's id is the primary key, which enforces the 1:1
    relationship; the participant row holds the witness's ordinal, snapshot
    and address. A witness recalled by the opposing party is a new participant
    with its own row.
    """

    # Replaces BaseModel's own UUID key.
    id = None
    case_participant = models.OneToOneField(
        CaseParticipant, primary_key=True, on_delete=models.CASCADE, related_name="witness"
    )
    # RESTRICT: a caller cannot be deleted on its own, but deleting the whole
    # case still cascades through both participants.
    called_by_participant = models.ForeignKey(
        CaseParticipant, on_delete=models.RESTRICT, related_name="witnesses_called"
    )
    what_will_witness_prove = models.TextField()
    additional_details = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        verbose_name_plural = "witnesses"

    def __str__(self):
        return f"Witness {self.case_participant_id} called by {self.called_by_participant_id}"

    def clean_fields(self, exclude=None):
        """Trim the statement, so a whitespace-only one is rejected as missing."""
        if self.what_will_witness_prove:
            self.what_will_witness_prove = self.what_will_witness_prove.strip()
        super().clean_fields(exclude=exclude)

    def clean(self):
        """Apply the rules the database cannot express (spec 0020 §4.5.2).

        The participant must be a witness, called by a complainant or an
        accused on the same case. Whether the caller is still active matters
        only while the witness is, so a removed witness can still be edited.
        While active, a person cannot be a witness twice for the same caller.
        Every broken rule is reported, not just the first one per field.
        """
        super().clean()
        if not (self.case_participant_id and self.called_by_participant_id):
            return
        witness, caller = self.case_participant, self.called_by_participant
        _raise_broken_rules(
            [
                (
                    "case_participant",
                    witness.role == ParticipantRole.WITNESS,
                    NOT_A_WITNESS_MESSAGE,
                ),
                ("called_by_participant", caller.role in INSTITUTION_ROLES, PARTY_ROLE_MESSAGE),
                ("called_by_participant", caller.case_id == witness.case_id, SAME_CASE_MESSAGE),
                (
                    "called_by_participant",
                    not witness.is_active or caller.is_active,
                    ACTIVE_PARTICIPANT_MESSAGE,
                ),
                (
                    "called_by_participant",
                    not self._called_twice(),
                    WITNESS_CALLED_TWICE_MESSAGE,
                ),
            ]
        )

    def _called_twice(self):
        """Return whether the person is already an active witness for this caller."""
        witness = self.case_participant
        if not (witness.is_active and witness.person_id):
            return False
        return (
            Witness.objects.filter(
                called_by_participant_id=self.called_by_participant_id,
                case_participant__person_id=witness.person_id,
                case_participant__is_active=True,
            )
            .exclude(pk=self.pk)
            .exists()
        )


class PoaMandate(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """The authority one participant holds to act for another (spec 0020 §5).

    One row per holder and represented party: a holder acting for two of three
    complainants has two rows. ``case`` repeats the participants' case so
    "every mandate on this case" needs no join. Revoking is a soft delete
    (``is_active = False``, ``revoked_at`` set): who had authority when is part
    of the case record.
    """

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="poa_mandates")
    poa_participant = models.ForeignKey(
        CaseParticipant, on_delete=models.CASCADE, related_name="poa_mandates_held"
    )
    represented_participant = models.ForeignKey(
        CaseParticipant, on_delete=models.CASCADE, related_name="poa_mandates_granted"
    )
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        verbose_name = "POA mandate"
        constraints = [
            models.CheckConstraint(
                check=~Q(poa_participant=F("represented_participant")),
                name="cases_poa_mandate_not_self",
                violation_error_message=PARTICIPANT_MANDATE_FOR_SELF_MESSAGE,
            ),
            models.UniqueConstraint(
                fields=["poa_participant", "represented_participant"],
                condition=Q(is_active=True),
                name="cases_poa_mandate_unique_active",
                violation_error_message=DUPLICATE_MANDATE_MESSAGE,
            ),
        ]
        indexes = [models.Index(fields=["case", "is_active"])]

    def __str__(self):
        return f"POA {self.poa_participant_id} for {self.represented_participant_id}"

    def clean(self):
        """Apply the rules the database cannot express (spec 0020 §5.2, §14.1).

        The holder must be a POA holder and the represented party a complainant
        or an accused, both on this mandate's case, and not the same person.
        Whether the represented party is still active matters only while the
        mandate is, so a revoked mandate can still be edited. Every broken rule
        is reported, not just the first one per field.
        """
        super().clean()
        if not (self.case_id and self.poa_participant_id and self.represented_participant_id):
            return
        holder, represented = self.poa_participant, self.represented_participant
        _raise_broken_rules(
            [
                (
                    "poa_participant",
                    holder.role == ParticipantRole.POA_HOLDER,
                    NOT_A_POA_HOLDER_MESSAGE,
                ),
                ("poa_participant", holder.case_id == self.case_id, SAME_CASE_MESSAGE),
                (
                    "represented_participant",
                    represented.role in INSTITUTION_ROLES,
                    PARTY_ROLE_MESSAGE,
                ),
                (
                    "represented_participant",
                    represented.case_id == self.case_id,
                    SAME_CASE_MESSAGE,
                ),
                (
                    "represented_participant",
                    not self.is_active or represented.is_active,
                    ACTIVE_PARTICIPANT_MESSAGE,
                ),
                (
                    "represented_participant",
                    not holder.person_id or holder.person_id != represented.person_id,
                    MANDATE_FOR_SELF_MESSAGE,
                ),
            ]
        )


class Representation(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """An advocate acting for one party in one case (spec 0020 §6).

    One row per advocate and client: an advocate for three complainants has
    three rows, so "who does this advocate represent" is a plain filter.
    ``case`` repeats the client's case so "every advocate on this case" needs
    no join. ``to_date`` records when the representation ended; ``is_active =
    False`` alone marks an administrative removal.
    """

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="representations")
    # PROTECT: removing an advocate must not erase who represented whom.
    advocate = models.ForeignKey(
        "users.AdvocateProfile", on_delete=models.PROTECT, related_name="representations"
    )
    case_participant = models.ForeignKey(
        CaseParticipant, on_delete=models.CASCADE, related_name="representations"
    )
    from_date = models.DateTimeField(default=timezone.now)
    to_date = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(
                fields=["advocate", "case_participant"],
                condition=Q(is_active=True),
                name="cases_representation_unique_active",
                violation_error_message=DUPLICATE_REPRESENTATION_MESSAGE,
            ),
        ]
        indexes = [
            models.Index(fields=["case", "is_active"]),
            models.Index(fields=["advocate", "is_active"]),
            models.Index(fields=["case_participant", "is_active"]),
        ]

    def __str__(self):
        return f"Advocate {self.advocate_id} for {self.case_participant_id}"

    def clean(self):
        """Apply the rules the database cannot express (spec 0020 §6.2, §14.1).

        The advocate must be approved and the client a complainant or an
        accused on this representation's case, and not the advocate themselves.
        Whether the client is still active, not appearing in person, and not on
        the other side from another client of the advocate matters only while
        the representation is, so an ended one can still be edited.
        Every broken rule is reported, not just the first one per field.
        """
        super().clean()
        if not (self.case_id and self.advocate_id and self.case_participant_id):
            return
        advocate, client = self.advocate, self.case_participant
        client_user_id = client.person.user_id if client.person_id else None
        _raise_broken_rules(
            [
                (
                    "advocate",
                    advocate.approval_status == ApprovalStatus.ACCEPTED,
                    ADVOCATE_NOT_APPROVED_MESSAGE,
                ),
                ("case_participant", client.role in INSTITUTION_ROLES, PARTY_ROLE_MESSAGE),
                ("case_participant", client.case_id == self.case_id, SAME_CASE_MESSAGE),
                (
                    "case_participant",
                    not self.is_active or client.is_active,
                    ACTIVE_PARTICIPANT_MESSAGE,
                ),
                (
                    "case_participant",
                    not self.is_active or not client.is_party_in_person,
                    PARTY_IN_PERSON_MESSAGE,
                ),
                (
                    "case_participant",
                    not client_user_id or client_user_id != advocate.user_id,
                    ADVOCATE_FOR_SELF_MESSAGE,
                ),
                (
                    "case_participant",
                    not self.is_active or not self._acts_for_other_side(client),
                    ADVOCATE_BOTH_SIDES_MESSAGE,
                ),
            ]
        )

    def _acts_for_other_side(self, client):
        """Return whether the advocate actively represents a party opposing ``client`` here."""
        opposing_role = OPPOSING_ROLES.get(client.role)
        return (
            opposing_role is not None
            and Representation.objects.active()
            .filter(
                case_id=self.case_id,
                advocate_id=self.advocate_id,
                case_participant__role=opposing_role,
            )
            .exclude(pk=self.pk)
            .exists()
        )


class CaseDocument(BaseModel, BaseActivatableModel, BaseAuditableModel):
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

    def clean(self):
        """Accept only a document type the case's type accepts, as the API does."""
        super().clean()
        if self.case_id and self.document_type:
            allowed = get_config(self.case.case_type).document_types
            if self.document_type not in allowed:
                raise ValidationError(
                    {"document_type": f"Not accepted for {self.case.case_type} cases."}
                )


class ChequeBounceCase(BaseModel, BaseAuditableModel):
    """Cheque bounce details, one row per case (spec 0020 §10).

    The case id is the primary key, which enforces the 1:1 relationship.
    Each JSON column holds one section of the filing form; the editable ones
    are listed in ``case_types.CASE_TYPES``.
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

    def __str__(self):
        return f"Cheque bounce details for {self.case_id}"

    def clean(self):
        """Check each filled-in section against its schema, as the API does.

        A section left empty (``{}``) is not yet filled in, which is allowed:
        the row is created empty with the case.
        """
        super().clean()
        if not self.case_id:
            return
        schemas = get_config(self.case.case_type).section_schemas
        errors = {
            section: [str(problem) for problem in problems]
            for section, schema in schemas.items()
            if getattr(self, section)
            and (problems := schema_errors(schema, getattr(self, section)))
        }
        if errors:
            raise ValidationError(errors)


class CaseEvidence(BaseModel, BaseActivatableModel, BaseAuditableModel):
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

    def clean(self):
        """Apply the API's rules, so the admin cannot save what the API would refuse.

        The case's type must accept the evidence type, ``evidence_info`` must
        match its schema, and a linked document must be an active document of
        the same case.
        """
        super().clean()
        if not self.case_id:
            return
        errors = {}
        schemas = get_config(self.case.case_type).evidence_schemas
        if self.evidence_type not in schemas:
            errors["evidence_type"] = f"Not accepted for {self.case.case_type} cases."
        elif problems := schema_errors(schemas[self.evidence_type], self.evidence_info):
            errors["evidence_info"] = [str(problem) for problem in problems]
        if self.case_document_id and not (
            self.case_document.case_id == self.case_id and self.case_document.is_active
        ):
            errors["case_document"] = "Must be an active document of the same case."
        if errors:
            raise ValidationError(errors)
