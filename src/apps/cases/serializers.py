"""Case filing serializers (spec 0021)."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.address.models import Address
from apps.api import errors as api_errors
from apps.files import documents
from apps.organizations.models import Organization
from apps.parties.models import (
    MAX_AGE,
    Gender,
    Institution,
    Person,
    contact_number_validator,
    phone_number_validator,
)

from . import errors
from .models import (
    ADDRESS_REQUIRED_MESSAGE,
    COMPLAINANT_ONLY_MESSAGE,
    CONTACT_UNKNOWN_MESSAGE,
    DESIGNATION_NOT_ALLOWED_MESSAGE,
    DESIGNATION_REQUIRED_MESSAGE,
    EMPTY_TEXT_MESSAGE,
    INSTITUTION_CONTACTS_MESSAGE,
    INSTITUTION_ROLES,
    NAME_REQUIRED_MESSAGE,
    PERMANENT_ADDRESS_MESSAGE,
    WITNESS_NAME_OR_DESIGNATION_MESSAGE,
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    ContactType,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
    WitnessSide,
    has_visible_text,
    police_station_problems,
)
from .services.case_types import CaseType, DocumentType, EvidenceType
from .services.contacts import contacts_of, first


class RejectUnknownFieldsMixin:
    """Refuses fields the serializer does not declare, so they are not silently ignored.

    Checked before the serializer's own ``validate``; ``unknown_field_message``
    is the error each unknown field gets.
    """

    unknown_field_message = "This field is not accepted."

    def validate(self, attrs):
        """Refuse every field not declared on the serializer."""
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise errors.FIELD_NOT_ACCEPTED.validation_error(
                {field: [self.unknown_field_message] for field in unknown}
            )
        return super().validate(attrs)


class PartialUpdateSerializer(RejectUnknownFieldsMixin, serializers.Serializer):
    """Base body of a PATCH: any declared field, at least one, and nothing else.

    A field left out is kept. The views take JSON only, so a field left out is
    never read as an empty form value.
    """

    unknown_field_message = "This field cannot be changed."

    def validate(self, attrs):
        """Require at least one change."""
        attrs = super().validate(attrs)
        if not attrs:
            raise api_errors.REQUIRED.validation_error("Send at least one field to change.")
        return attrs


def _require_visible_text(html):
    """Refuse rich text that renders as nothing; ``None`` (cleared) passes."""
    if html is not None and not has_visible_text(html):
        raise api_errors.BLANK.validation_error(EMPTY_TEXT_MESSAGE)
    return html


def _require_each_once(ids):
    """Refuse a list of participant ids that names a party more than once."""
    if len(set(ids)) != len(ids):
        raise errors.DUPLICATE_PARTICIPANT.validation_error()
    return ids


@extend_schema_field(OpenApiTypes.BINARY)
class UploadField(serializers.FileField):
    """A file upload.

    drf-spectacular documents a plain ``FileField`` as a URL string, so
    Swagger would show a text box; ``binary`` gives it a file picker.
    """


class DraftSessionSerializer(serializers.Serializer):
    """A draft session.

    The request takes ``case_type`` and, optionally, the ``court_id`` of the
    court (an Organization) to file in; the response adds the rest.
    """

    draft_session_id = serializers.UUIDField(read_only=True)
    case_type = serializers.ChoiceField(choices=CaseType.choices)
    court_id = serializers.UUIDField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)

    def validate_court_id(self, court_id):
        """Accept only an existing, active organization."""
        if court_id is not None and not Organization.objects.active().filter(pk=court_id).exists():
            raise api_errors.DOES_NOT_EXIST.validation_error("No active court with this id.")
        return court_id


class CaseSerializer(serializers.ModelSerializer):
    """Case metadata, for listings and the join-by-number lookup."""

    case_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = Case
        fields = [
            "case_id",
            "case_type",
            "filing_number",
            "case_number",
            "cnr_number",
            "status",
            "court_id",
            "filed_at",
            "registered_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CaseListItemSerializer(CaseSerializer):
    """A case in GET /cases: its metadata, plus what the Drafts list shows.

    Reads the annotations ``services.with_list_fields`` adds.
    ``party_title`` is "first complainant vs first accused", by their party
    names on the case (an institution's name when there is one), and ``null``
    until both have been added.
    ``cause_of_action_date`` is ``null`` until the details section holding it
    is saved.
    """

    party_title = serializers.SerializerMethodField()
    cause_of_action_date = serializers.DateField(read_only=True, allow_null=True)

    class Meta(CaseSerializer.Meta):
        """Meta options."""

        fields = [*CaseSerializer.Meta.fields, "party_title", "cause_of_action_date"]
        read_only_fields = fields

    def get_party_title(self, case) -> str | None:
        """First complainant vs first accused; null while either side has no one."""
        if case.first_complainant_name and case.first_accused_name:
            return f"{case.first_complainant_name} vs {case.first_accused_name}"
        return None


class CaseDocumentUploadSerializer(serializers.Serializer):
    """Multipart body of POST /cases/{id}/documents.

    ``document_type`` must be a known type here; whether the case's type
    accepts it is checked by the service.
    """

    file = UploadField()
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    # Whose document it is, or which evidence item it supports; checked against
    # the document type when saving.
    case_participant_id = serializers.UUIDField(required=False)
    case_evidence_id = serializers.UUIDField(required=False)
    # Kept in the document's additional_details. allow_null, so a multipart
    # form that leaves it out sends nothing rather than False.
    is_digital = serializers.BooleanField(required=False, allow_null=True)
    # Blank means none, as on PATCH.
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_file(self, upload):
        """Accept a real PDF, JPEG, PNG, WebP or HEIC file within the size limit.

        Uses the project's shared check: the declared type and the file name
        are hints, the content's leading bytes decide, so a renamed or
        mislabelled file is refused. WebP and HEIC are what phone cameras
        save, so case documents take them; other uploads do not.
        """
        error = documents.document_error(upload, documents.CASE_DOCUMENT_FORMATS)
        if error:
            raise serializers.ValidationError(error)
        return upload


class CaseDocumentUpdateSerializer(PartialUpdateSerializer):
    """Body of PATCH /case-documents/{id} (spec 0021 §3.3).

    The file and the document type cannot change. ``null`` removes a link or a
    detail.
    """

    case_participant_id = serializers.UUIDField(required=False, allow_null=True)
    case_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    is_digital = serializers.BooleanField(required=False, allow_null=True)
    display_name = serializers.CharField(
        max_length=255, required=False, allow_null=True, allow_blank=True
    )


class CaseDocumentSerializer(serializers.ModelSerializer):
    """A case document with its file's metadata and links."""

    case_document_id = serializers.UUIDField(source="id", read_only=True)
    file_name = serializers.CharField(source="document.file_name", read_only=True)
    file_size = serializers.IntegerField(source="document.file_size", read_only=True)
    is_digital = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_is_digital(self, document):
        """Return whether the uploader said the file was born digital, or ``None``."""
        return document.additional_details.get("is_digital")

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_display_name(self, document):
        """Return the name the uploader gave the document, or ``None``."""
        return document.additional_details.get("display_name")

    class Meta:
        """Meta options."""

        model = CaseDocument
        fields = [
            "case_id",
            "case_document_id",
            "document_id",
            "document_type",
            "case_participant_id",
            "case_evidence_id",
            "file_name",
            "file_size",
            "is_digital",
            "display_name",
            "created_at",
        ]
        read_only_fields = fields


class EvidenceCreateSerializer(serializers.Serializer):
    """Body of POST /cases/{id}/evidence.

    ``evidence_info`` is checked against the case type's schema by the service.
    """

    evidence_type = serializers.ChoiceField(choices=EvidenceType.choices)
    case_document_id = serializers.UUIDField(required=False, allow_null=True)
    evidence_info = serializers.DictField()


class EvidenceUpdateSerializer(PartialUpdateSerializer):
    """Body of PATCH /case-evidence/{id}: either field, or both.

    ``case_document_id`` links an uploaded document to the evidence, or unlinks
    it when ``null``; leaving it out keeps the current link. The evidence type
    cannot change.
    """

    evidence_info = serializers.DictField(required=False)
    case_document_id = serializers.UUIDField(required=False, allow_null=True)


class CaseEvidenceSerializer(serializers.ModelSerializer):
    """A piece of evidence."""

    case_evidence_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = CaseEvidence
        fields = [
            "case_evidence_id",
            "case_id",
            "case_document_id",
            "evidence_type",
            "ordinal",
            "evidence_info",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class CodeLabelSerializer(serializers.Serializer):
    """A code with its display label."""

    code = serializers.CharField()
    label = serializers.CharField()


class SectionDescriptionSerializer(serializers.Serializer):
    """A details section and the JSON Schema its data is validated against."""

    code = serializers.CharField()
    schema = serializers.DictField()


class EvidenceTypeDescriptionSerializer(CodeLabelSerializer):
    """An evidence type and the JSON Schema its ``evidence_info`` is validated against."""

    schema = serializers.DictField()


class CaseTypeDescriptionSerializer(serializers.Serializer):
    """What one case type accepts, for clients to build their forms from."""

    case_type = serializers.CharField()
    label = serializers.CharField()
    sections = SectionDescriptionSerializer(many=True)
    document_types = CodeLabelSerializer(many=True)
    # Codes that must each be uploaded before the case can be submitted.
    required_document_types = serializers.ListField(child=serializers.CharField())
    # Codes that must each have at least one active evidence item.
    required_evidence_types = serializers.ListField(child=serializers.CharField())
    evidence_types = EvidenceTypeDescriptionSerializer(many=True)


class CaseAffidavitSerializer(serializers.Serializer):
    """Body and response of PUT /cases/{id}/affidavit: the case's affidavit.

    Rich-text editor output, stored as sent; it replaces what was stored.
    """

    case_id = serializers.UUIDField(read_only=True)
    affidavit = serializers.CharField()

    def validate_affidavit(self, value):
        """Refuse editor output with no text in it."""
        return _require_visible_text(value)


class DetailsSectionSerializer(serializers.Serializer):
    """Response of PUT /cases/{id}/details/{section}: the section as saved."""

    case_id = serializers.UUIDField()
    section = serializers.CharField()
    data = serializers.DictField()


# Parties (spec 0021 §4)


class AddressInputSerializer(serializers.Serializer):
    """An address in a party write.

    Only the shape is checked here; the address service normalizes the values
    and applies the address rules (pincode format and so on) when saving.
    """

    line1 = serializers.CharField(max_length=255)
    city = serializers.CharField(max_length=100)
    pincode = serializers.CharField(max_length=16)
    district = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    # Optional here; ``models.police_station_error`` requires it for an accused
    # or a witness.
    police_station = serializers.CharField(max_length=255, required=False, allow_blank=True)


class PersonInputSerializer(serializers.ModelSerializer):
    """A person named in a party write. The model's rules apply again when saving.

    Their mobile numbers and emails are the party's ``mobile_numbers`` and
    ``email_addresses``; a new person row keeps the first of each.
    """

    class Meta:
        """Meta options."""

        model = Person
        fields = [
            "name",
            "date_of_birth",
            "age",
            "gender",
            "relation",
            "relative_name",
            "disability_status",
        ]


class ContactListsSerializer(serializers.Serializer):
    """Mobile numbers, emails and addresses, each a list in order; the first is the primary.

    Stored as ``CaseContact`` rows (spec 0020 §4.6). A list left out is not
    changed; on PATCH, a list sent replaces the whole list. A person's mobile
    number is in E.164 form; an institution's may be a landline
    (``mobile_number_validator``). Nothing may be given twice in one list.
    """

    mobile_number_validator = phone_number_validator

    mobile_numbers = serializers.ListField(
        child=serializers.CharField(max_length=20), required=False
    )
    email_addresses = serializers.ListField(
        child=serializers.EmailField(max_length=256), required=False
    )
    addresses = serializers.ListField(child=AddressInputSerializer(), required=False)

    def validate_mobile_numbers(self, values):
        """Check each number's form, and that none is repeated."""
        problems = {}
        for index, value in enumerate(values):
            try:
                self.mobile_number_validator(value)
            except DjangoValidationError as exc:
                problems[index] = exc.messages
        if problems:
            raise serializers.ValidationError(problems)
        return _require_unique(values)

    def validate_email_addresses(self, values):
        """Refuse an email given twice, in any case."""
        return _require_unique(values, key=str.lower)


def _require_unique(values, key=None):
    """Refuse a list with the same value twice, reporting each repeat at its position."""
    seen = set()
    problems = {}
    for index, value in enumerate(values):
        compared = key(value) if key else value
        if compared in seen:
            problems[index] = [errors.coded(errors.DUPLICATE_CONTACT)]
        seen.add(compared)
    if problems:
        raise serializers.ValidationError(problems)
    return values


class InstitutionContactsSerializer(ContactListsSerializer):
    """An institution's own contacts on one case, changed without re-linking it.

    Its mobile numbers may be landlines.
    """

    mobile_number_validator = contact_number_validator


class InstitutionInputSerializer(ContactListsSerializer, serializers.ModelSerializer):
    """An institution named in a party write, with its contacts for this case.

    PAN and CIN are not checked for uniqueness: an existing institution with
    either is reused rather than refused (spec 0020 §3.4). Their format is
    checked by the model, after spaces are removed and letters uppercased.
    One of them, or ``pan_cin_skip_declared``, is required, and the
    declaration cannot come with either (``parties.models.pan_cin_errors``).
    Its mobile numbers may be landlines.
    """

    mobile_number_validator = contact_number_validator

    pan = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    cin = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        """Meta options."""

        model = Institution
        fields = [
            "entity_type",
            "entity_name",
            "pan",
            "cin",
            "pan_cin_skip_declared",
            "mobile_numbers",
            "email_addresses",
            "addresses",
        ]


CONTACT_LIST_FIELDS = ("mobile_numbers", "email_addresses", "addresses")


class PartySerializer(ContactListsSerializer):
    """Base body of a party write.

    The individual is ``person`` (someone the filer names) or ``"self": true``
    (the filer). ``self`` is returned as ``is_self``. A named person needs a
    name unless ``person_name_required`` is off (a witness, who may give a
    designation instead). ``mobile_numbers``, ``email_addresses`` and
    ``addresses`` are the individual's.
    """

    person_name_required = True

    person = PersonInputSerializer(required=False)
    additional_details = serializers.DictField(default=dict)

    def get_fields(self):
        """Add ``self``, which cannot be declared as a class attribute."""
        fields = super().get_fields()
        fields["self"] = serializers.BooleanField(default=False)
        return fields

    def validate(self, attrs):
        """Return ``self`` as ``is_self``; require a named person's name."""
        attrs = super().validate(attrs)
        attrs["is_self"] = attrs.pop("self")
        person = attrs.get("person")
        if self.person_name_required and person is not None and not person.get("name"):
            raise api_errors.REQUIRED.validation_error(
                {"person": {"name": [NAME_REQUIRED_MESSAGE]}}
            )
        return attrs


class ParticipantCreateSerializer(PartySerializer):
    """Body of POST /cases/{id}/complainants and /accused (spec 0021 §4.1, §4.2).

    Either individual may be left out when ``institution`` is given. An
    individual needs at least one address; an institution needs at least one
    of its own, and the person acting for it may give theirs. The role being
    added is passed in the context as ``role``.
    """

    institution = InstitutionInputSerializer(required=False)
    designation = serializers.CharField(max_length=128, required=False, allow_null=True)
    # An individual complainant's, when it differs from their first address.
    permanent_address = AddressInputSerializer(required=False)
    is_party_in_person = serializers.BooleanField(default=False)
    # Accused only; yes when left out.
    resides_within_jurisdiction = serializers.BooleanField(required=False)
    # Accused only: the filer does not know their phone number or email.
    contact_details_unknown_declared = serializers.BooleanField(required=False)
    # Complainants only; rich-text editor output.
    party_in_person_affidavit = serializers.CharField(required=False, allow_null=True)

    def validate_party_in_person_affidavit(self, value):
        """Refuse editor output with no text in it."""
        return _require_visible_text(value)

    def validate(self, attrs):
        """Check the fields that only make sense together, for the role being added."""
        attrs = super().validate(attrs)
        role = self.context["role"]
        has_individual = attrs["is_self"] or "person" in attrs
        problems = {}
        if attrs["is_self"] and "person" in attrs:
            problems["self"] = [errors.coded(errors.PERSON_AND_SELF)]
        elif attrs["is_self"] and role == ParticipantRole.ACCUSED:
            problems["self"] = [errors.coded(errors.SELF_AS_ACCUSED)]
        elif not has_individual and "institution" not in attrs:
            problems["person"] = [
                errors.coded(api_errors.REQUIRED, "Send person, self or institution.")
            ]
        if "institution" in attrs and role not in INSTITUTION_ROLES:
            problems["institution"] = [errors.coded(errors.INSTITUTION_NOT_ALLOWED)]
        if (
            role == ParticipantRole.ACCUSED
            and has_individual
            and "institution" in attrs
            and not attrs.get("designation")
        ):
            problems["designation"] = [
                errors.coded(api_errors.REQUIRED, DESIGNATION_REQUIRED_MESSAGE)
            ]
        if attrs.get("designation") and not (has_individual and "institution" in attrs):
            problems["designation"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, DESIGNATION_NOT_ALLOWED_MESSAGE)
            ]
        if "permanent_address" in attrs and (
            role != ParticipantRole.COMPLAINANT or "institution" in attrs or not has_individual
        ):
            problems["permanent_address"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, PERMANENT_ADDRESS_MESSAGE)
            ]
        for field in ("resides_within_jurisdiction", "contact_details_unknown_declared"):
            if field in attrs and role != ParticipantRole.ACCUSED:
                problems[field] = [
                    errors.coded(errors.FIELD_NOT_APPLICABLE, "Only for an accused.")
                ]
        institution = attrs.get("institution")
        if institution is not None and not has_individual:
            for field in CONTACT_LIST_FIELDS:
                if attrs.get(field):
                    problems[field] = [
                        errors.coded(errors.FIELD_NOT_APPLICABLE, INSTITUTION_CONTACTS_MESSAGE)
                    ]
        if problem := police_station_problems(role, attrs.get("addresses")):
            problems["addresses"] = problem
        if institution is not None and "institution" not in problems:
            if not institution.get("addresses"):
                problems["institution"] = {
                    "addresses": [errors.coded(api_errors.REQUIRED, ADDRESS_REQUIRED_MESSAGE)]
                }
            elif problem := police_station_problems(role, institution["addresses"]):
                problems["institution"] = {"addresses": problem}
        elif institution is None and not attrs.get("addresses"):
            problems["addresses"] = [errors.coded(api_errors.REQUIRED, ADDRESS_REQUIRED_MESSAGE)]
        if (
            "contact_details_unknown_declared" not in problems
            and attrs.get("contact_details_unknown_declared")
            and any(
                contacts.get(field)
                for contacts in (attrs, institution or {})
                for field in ("mobile_numbers", "email_addresses")
            )
        ):
            problems["contact_details_unknown_declared"] = [
                errors.coded(api_errors.INVALID, CONTACT_UNKNOWN_MESSAGE)
            ]
        if attrs.get("party_in_person_affidavit") and role != ParticipantRole.COMPLAINANT:
            problems["party_in_person_affidavit"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, COMPLAINANT_ONLY_MESSAGE)
            ]
        if problems:
            raise serializers.ValidationError(problems)
        return attrs


class IndividualPartySerializer(RejectUnknownFieldsMixin, PartySerializer):
    """Base body for a party who is always an individual, never an institution.

    Fields it does not declare are refused, so an ``institution`` sent anyway
    is not silently ignored.
    """

    def validate(self, attrs):
        """Require exactly one of ``person`` and ``self``."""
        attrs = super().validate(attrs)
        problems = {}
        if attrs["is_self"] and "person" in attrs:
            problems["self"] = [errors.coded(errors.PERSON_AND_SELF)]
        elif not attrs["is_self"] and "person" not in attrs:
            problems["person"] = [errors.coded(api_errors.REQUIRED, "Send person or self.")]
        if problems:
            raise serializers.ValidationError(problems)
        return attrs


class WitnessCreateSerializer(IndividualPartySerializer):
    """Body of POST /cases/{id}/witnesses (spec 0021 §4.3).

    ``side`` says whether the complainant or the accused calls the witness.
    At least one address is required, each with a police station. ``designation`` is the
    witness's job title, kept on the participant; a named person needs a name
    or a designation. The mobile number is optional. ``additional_details`` is
    stored on the witness row.
    """

    person_name_required = False

    side = serializers.ChoiceField(choices=WitnessSide.choices)
    what_will_witness_prove = serializers.CharField(required=False, allow_blank=True)
    designation = serializers.CharField(max_length=128, required=False, allow_null=True)

    def validate(self, attrs):
        """Require a name or designation, and an address with a police station."""
        attrs = super().validate(attrs)
        problems = {}
        person = attrs.get("person")
        if person is not None and not (person.get("name") or attrs.get("designation")):
            problems["person"] = {
                "name": [errors.coded(api_errors.REQUIRED, WITNESS_NAME_OR_DESIGNATION_MESSAGE)]
            }
        if not attrs.get("addresses"):
            problems["addresses"] = [errors.coded(api_errors.REQUIRED, ADDRESS_REQUIRED_MESSAGE)]
        elif problem := police_station_problems(ParticipantRole.WITNESS, attrs["addresses"]):
            problems["addresses"] = problem
        if problems:
            raise serializers.ValidationError(problems)
        return attrs


class PoaHolderCreateSerializer(IndividualPartySerializer):
    """Body of POST /cases/{id}/poa-holders (spec 0021 §4.5).

    At least one address is required. One mandate is created per represented party;
    whether each is an active complainant or accused of the case is checked
    when saving.
    """

    represented_participant_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )
    # The holder's, when it differs from their first address.
    permanent_address = AddressInputSerializer(required=False)

    def validate_represented_participant_ids(self, value):
        """Require each represented party once."""
        return _require_each_once(value)

    def validate(self, attrs):
        """Require an address."""
        attrs = super().validate(attrs)
        if not attrs.get("addresses"):
            raise api_errors.REQUIRED.validation_error({"addresses": [ADDRESS_REQUIRED_MESSAGE]})
        return attrs


class PoaHolderCreatedSerializer(serializers.Serializer):
    """Response of POST /cases/{id}/poa-holders: the holder and their new mandates."""

    case_participant_id = serializers.UUIDField()
    poa_mandate_ids = serializers.ListField(child=serializers.UUIDField())
    person_id = serializers.UUIDField()
    role = serializers.CharField()


class PoaMandateSerializer(serializers.ModelSerializer):
    """A POA mandate, with the holder's name as recorded on the case."""

    poa_mandate_id = serializers.UUIDField(source="id", read_only=True)
    poa_holder_name = serializers.CharField(source="poa_participant.name_at_filing", read_only=True)

    class Meta:
        """Meta options."""

        model = PoaMandate
        fields = [
            "poa_mandate_id",
            "case_id",
            "poa_participant_id",
            "poa_holder_name",
            "represented_participant_id",
            "is_active",
            "granted_at",
            "revoked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AdvocateCreateSerializer(serializers.Serializer):
    """Body of POST /cases/{id}/advocates (spec 0021 §4.4).

    One representation is created per client; whether the advocate is
    approved and each client an active complainant or accused of the case is
    checked when saving.
    """

    advocate_id = serializers.UUIDField()
    client_participant_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)

    def validate_client_participant_ids(self, value):
        """Require each client once."""
        return _require_each_once(value)


class AdvocateCreatedSerializer(serializers.Serializer):
    """Response of POST /cases/{id}/advocates: the new representations."""

    representation_ids = serializers.ListField(child=serializers.UUIDField())
    advocate_id = serializers.UUIDField()


class RepresentationSerializer(serializers.ModelSerializer):
    """A representation, with the advocate's name and bar registration number."""

    representation_id = serializers.UUIDField(source="id", read_only=True)
    advocate_name = serializers.CharField(source="advocate.name", read_only=True)
    bar_registration_id = serializers.CharField(
        source="advocate.bar_registration_id", read_only=True
    )
    client_participant_id = serializers.UUIDField(source="case_participant_id", read_only=True)

    class Meta:
        """Meta options."""

        model = Representation
        fields = [
            "representation_id",
            "case_id",
            "advocate_id",
            "advocate_name",
            "bar_registration_id",
            "client_participant_id",
            "is_active",
            "from_date",
            "to_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ParticipantUpdateSerializer(ContactListsSerializer, PartialUpdateSerializer):
    """Body of PATCH /case-participants/{id} (spec 0021 §4.1).

    Changes the case's copy of the party's details; the institution row is
    never changed, and the person only by ``permanent_address`` and
    ``disability_status``. The role and person cannot change. A contact list
    sent replaces the person's whole list. ``institution_contacts`` replaces
    the institution's own lists in this case and nothing else; ``institution``
    re-links an institution participant to the one its PAN or CIN names, and
    may carry the lists too (spec 0021 §4.1).
    """

    # ``null`` clears it; only a witness with a designation may have no name.
    name_at_filing = serializers.CharField(max_length=256, required=False, allow_null=True)
    gender_at_filing = serializers.ChoiceField(
        choices=Gender.choices, required=False, allow_null=True
    )
    age_at_filing = serializers.IntegerField(
        min_value=0, max_value=MAX_AGE, required=False, allow_null=True
    )
    designation_at_filing = serializers.CharField(max_length=128, required=False, allow_null=True)
    # People only; set on the person. ``null`` means not answered.
    disability_status = serializers.BooleanField(required=False, allow_null=True)
    # Institutions only. For an institution with no person acting for it,
    # ``name_at_filing`` and ``entity_name_at_filing`` are kept the same.
    entity_name_at_filing = serializers.CharField(max_length=256, required=False)
    # Individual complainants and POA holders only. Set on the person, which
    # holds current data; it has no snapshot on the participant. ``null``
    # makes it the participant's first address again.
    permanent_address = AddressInputSerializer(required=False, allow_null=True)
    is_party_in_person = serializers.BooleanField(required=False)
    resides_within_jurisdiction = serializers.BooleanField(required=False)
    contact_details_unknown_declared = serializers.BooleanField(required=False)
    # Complainants only; ``null`` clears it.
    party_in_person_affidavit = serializers.CharField(required=False, allow_null=True)
    additional_details = serializers.DictField(required=False)
    # Institution participants only. ``institution`` re-links the participant;
    # ``institution_contacts`` changes only the institution's contacts here.
    institution = InstitutionInputSerializer(required=False)
    institution_contacts = InstitutionContactsSerializer(required=False)
    # Witnesses only (spec 0021 §4.3); they change the witness row.
    side = serializers.ChoiceField(choices=WitnessSide.choices, required=False)
    what_will_witness_prove = serializers.CharField(required=False, allow_blank=True)

    def validate_party_in_person_affidavit(self, value):
        """Refuse editor output with no text in it; ``null`` clears it."""
        return _require_visible_text(value)


class WitnessSerializer(serializers.ModelSerializer):
    """What only a witness has (spec 0020 §4.5)."""

    class Meta:
        """Meta options."""

        model = Witness
        fields = ["side", "what_will_witness_prove", "additional_details"]
        read_only_fields = fields


class AddressSerializer(serializers.ModelSerializer):
    """An address, as recorded for a participant on the case."""

    address_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = Address
        fields = ["address_id", "line1", "city", "district", "state", "pincode", "police_station"]
        read_only_fields = fields


class ContactListsOutSerializer(serializers.Serializer):
    """An owner's contacts in one case, each list in order: the first is the primary."""

    mobile_numbers = serializers.ListField(child=serializers.CharField())
    email_addresses = serializers.ListField(child=serializers.CharField())
    addresses = AddressSerializer(many=True)


def contact_lists(rows):
    """Return the three contact lists of ``rows`` (one owner's active contacts)."""
    rows = sorted(rows, key=lambda row: row.ordinal)
    return {
        "mobile_numbers": [r.value for r in rows if r.contact_type == ContactType.MOBILE_NUMBER],
        "email_addresses": [r.value for r in rows if r.contact_type == ContactType.EMAIL],
        "addresses": [
            AddressSerializer(r.address).data for r in rows if r.contact_type == ContactType.ADDRESS
        ],
    }


class ParticipantInstitutionSerializer(ContactListsOutSerializer, serializers.ModelSerializer):
    """The institution a participant is, as its row stores it, with its contacts in this case.

    PAN, CIN and the skip declaration are shown for a complainant only; an
    accused's form does not ask for them.
    """

    class Meta:
        """Meta options."""

        model = Institution
        fields = [
            "entity_name",
            "entity_type",
            "pan",
            "cin",
            "pan_cin_skip_declared",
            "mobile_numbers",
            "email_addresses",
            "addresses",
        ]
        read_only_fields = fields


class CaseParticipantSerializer(serializers.ModelSerializer):
    """A case participant: the case's copy of a party's details.

    The person is shown by id only. ``mobile_numbers``, ``email_addresses``
    and ``addresses`` are the person's on this case (empty for an institution
    alone). ``institution`` is the institution's row (``null`` for an
    individual), which a reused institution shares with other filings (spec
    0020 §3.4), with its own contacts on this case. ``witness`` is null for
    every role but a witness.
    """

    case_participant_id = serializers.UUIDField(source="id", read_only=True)
    mobile_numbers = serializers.SerializerMethodField()
    email_addresses = serializers.SerializerMethodField()
    addresses = serializers.SerializerMethodField()
    institution = serializers.SerializerMethodField()
    # The person's answer; null when not answered, or for an institution alone.
    disability_status = serializers.BooleanField(
        source="person.disability_status", read_only=True, allow_null=True
    )
    witness = WitnessSerializer(read_only=True, allow_null=True)

    class Meta:
        """Meta options."""

        model = CaseParticipant
        fields = [
            "case_participant_id",
            "case_id",
            "person_id",
            "institution_id",
            "role",
            "ordinal",
            "name_at_filing",
            "gender_at_filing",
            "age_at_filing",
            "designation_at_filing",
            "entity_name_at_filing",
            "mobile_numbers",
            "email_addresses",
            "addresses",
            "institution",
            "disability_status",
            "is_party_in_person",
            "resides_within_jurisdiction",
            "contact_details_unknown_declared",
            "party_in_person_affidavit",
            "additional_details",
            "witness",
            "has_signed",
            "signature_document_id",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    # Preview, validation and signing (spec 0021 §6–8)

    def _own(self, participant):
        return contact_lists(contacts_of(participant)[0])

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_mobile_numbers(self, participant):
        """Return the person's mobile numbers on this case, primary first."""
        return self._own(participant)["mobile_numbers"]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_email_addresses(self, participant):
        """Return the person's emails on this case, primary first."""
        return self._own(participant)["email_addresses"]

    @extend_schema_field(AddressSerializer(many=True))
    def get_addresses(self, participant):
        """Return the person's addresses on this case, written out, primary first."""
        return self._own(participant)["addresses"]

    @extend_schema_field(ParticipantInstitutionSerializer(allow_null=True))
    def get_institution(self, participant):
        """Return the institution's row and its contacts here; PAN and CIN for a complainant only."""
        if participant.institution is None:
            return None
        institution = participant.institution
        data = {
            "entity_name": institution.entity_name,
            "entity_type": institution.entity_type,
            "pan": institution.pan,
            "cin": institution.cin,
            "pan_cin_skip_declared": institution.pan_cin_skip_declared,
            **contact_lists(contacts_of(participant)[1]),
        }
        if participant.role != ParticipantRole.COMPLAINANT:
            data.update(pan=None, cin=None, pan_cin_skip_declared=None)
        return data


class PreviewParticipantSerializer(CaseParticipantSerializer):
    """A participant with the person's permanent address too.

    ``permanent_address`` is the person's (an individual complainant or POA
    holder), shown only when it differs from their first address: ``null``
    means the same as the residential address, or none.
    """

    permanent_address = serializers.SerializerMethodField()

    class Meta(CaseParticipantSerializer.Meta):
        """Meta options."""

        fields = [*CaseParticipantSerializer.Meta.fields, "permanent_address"]
        read_only_fields = fields

    @extend_schema_field(AddressSerializer(allow_null=True))
    def get_permanent_address(self, participant):
        """Return the person's permanent address when it differs from their first address."""
        person = participant.person
        if person is None or person.permanent_address_id is None:
            return None
        primary = first(contacts_of(participant)[0], ContactType.ADDRESS)
        if primary is not None and primary.address_id == person.permanent_address_id:
            return None
        return AddressSerializer(person.permanent_address).data


class CasePreviewSerializer(CaseSerializer):
    """GET /cases/{id}: the whole filing, from the case's own frozen copies.

    Reads the ``active_*`` lists and ``detail_sections`` that
    ``services.filing`` loads onto the case.
    """

    participants = PreviewParticipantSerializer(
        source="active_participants", many=True, read_only=True
    )
    representations = RepresentationSerializer(
        source="active_representations", many=True, read_only=True
    )
    poa_mandates = PoaMandateSerializer(source="active_poa_mandates", many=True, read_only=True)
    evidence = CaseEvidenceSerializer(source="active_evidence", many=True, read_only=True)
    documents = CaseDocumentSerializer(source="active_documents", many=True, read_only=True)
    # One key per section of the case's type; see GET /case-types/{case_type}.
    details = serializers.DictField(source="detail_sections", read_only=True)

    class Meta(CaseSerializer.Meta):
        """Meta options."""

        fields = [
            *CaseSerializer.Meta.fields,
            "affidavit",
            "participants",
            "representations",
            "poa_mandates",
            "evidence",
            "documents",
            "details",
        ]
        read_only_fields = fields


class ValidationErrorItemSerializer(serializers.Serializer):
    """One reason a case is not ready: the part of the filing, and why."""

    field = serializers.CharField()
    message = serializers.CharField()


class CaseValidationSerializer(serializers.Serializer):
    """Response of POST /cases/{id}/validate."""

    is_valid = serializers.BooleanField()
    errors = ValidationErrorItemSerializer(many=True)


class SignatureSerializer(serializers.Serializer):
    """Body of POST /cases/{id}/participants/{id}/sign.

    ``signature_document_id`` is the signed file a completed e-sign
    transaction stored (spec 0015).
    """

    signature_document_id = serializers.UUIDField()


class SignedSerializer(serializers.ModelSerializer):
    """Response of POST /cases/{id}/participants/{id}/sign.

    ``signed_at`` is the e-sign transaction's ``completed_at``, which
    ``services.filing.record_signature`` sets on the participant.
    """

    case_participant_id = serializers.UUIDField(source="id", read_only=True)
    signed_at = serializers.DateTimeField(read_only=True)

    class Meta:
        """Meta options."""

        model = CaseParticipant
        fields = ["case_participant_id", "has_signed", "signed_at", "signature_document_id"]
        read_only_fields = fields
