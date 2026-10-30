"""Case filing serializers (spec 0021)."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.address.models import Address
from apps.api import errors as api_errors
from apps.files import documents
from apps.organizations.models import Organization
from apps.parties.models import MAX_AGE, Gender, Institution, Person

from . import errors
from .models import (
    ADDRESS_REQUIRED_MESSAGE,
    COMPLAINANT_ONLY_MESSAGE,
    DESIGNATION_NOT_ALLOWED_MESSAGE,
    DESIGNATION_REQUIRED_MESSAGE,
    EMPTY_TEXT_MESSAGE,
    INSTITUTION_ROLES,
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
    has_visible_text,
)
from .services.case_types import CaseType, DocumentType, EvidenceType


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

    def validate_file(self, upload):
        """Accept a real PDF, JPEG or PNG within the size limit.

        Uses the project's shared check: the declared type and the file name
        are hints, the content's leading bytes decide, so a renamed or
        mislabelled file is refused.
        """
        error = documents.document_error(upload)
        if error:
            raise serializers.ValidationError(error)
        return upload


class CaseDocumentSerializer(serializers.ModelSerializer):
    """A case document with its file's metadata."""

    case_document_id = serializers.UUIDField(source="id", read_only=True)
    file_name = serializers.CharField(source="document.file_name", read_only=True)
    file_size = serializers.IntegerField(source="document.file_size", read_only=True)

    class Meta:
        """Meta options."""

        model = CaseDocument
        fields = [
            "case_id",
            "case_document_id",
            "document_id",
            "document_type",
            "file_name",
            "file_size",
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


class EvidenceUpdateSerializer(serializers.Serializer):
    """Body of PATCH /case-evidence/{id}: either field, or both.

    ``case_document_id`` links an uploaded document to the evidence, or unlinks
    it when ``null``; leaving it out keeps the current link. The evidence type
    cannot change.
    """

    evidence_info = serializers.DictField(required=False)
    case_document_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        """Require at least one change."""
        if not attrs:
            raise serializers.ValidationError("Send evidence_info, case_document_id, or both.")
        return attrs


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
    police_station = serializers.CharField(max_length=255)


class PersonInputSerializer(serializers.ModelSerializer):
    """A person named in a party write. The model's rules apply again when saving."""

    class Meta:
        """Meta options."""

        model = Person
        fields = [
            "name",
            "phone_number",
            "email_address",
            "date_of_birth",
            "age",
            "gender",
            "relation",
            "relative_name",
        ]


class InstitutionInputSerializer(serializers.ModelSerializer):
    """An institution named in a party write.

    PAN and CIN are not checked for uniqueness: an existing institution with
    either is reused rather than refused (spec 0020 §3.4). Their format is
    checked by the model, after spaces are removed and letters uppercased.
    """

    pan = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    cin = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        """Meta options."""

        model = Institution
        fields = ["entity_type", "entity_name", "pan", "cin", "contact_number", "email_address"]


class PartySerializer(serializers.Serializer):
    """Base body of a party write.

    The individual is ``person`` (someone the filer names) or ``"self": true``
    (the filer). ``self`` is returned as ``is_self``.
    """

    person = PersonInputSerializer(required=False)
    address = AddressInputSerializer(required=False)
    additional_details = serializers.DictField(default=dict)

    def get_fields(self):
        """Add ``self``, which cannot be declared as a class attribute."""
        fields = super().get_fields()
        fields["self"] = serializers.BooleanField(default=False)
        return fields

    def validate(self, attrs):
        """Return ``self`` as ``is_self``."""
        attrs = super().validate(attrs)
        attrs["is_self"] = attrs.pop("self")
        return attrs


class ParticipantCreateSerializer(PartySerializer):
    """Body of POST /cases/{id}/complainants and /accused (spec 0021 §4.1, §4.2).

    Either individual may be left out when ``institution`` is given. The role
    being added is passed in the context as ``role``.
    """

    institution = InstitutionInputSerializer(required=False)
    designation = serializers.CharField(max_length=128, required=False, allow_null=True)
    is_party_in_person = serializers.BooleanField(default=False)
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
        if "address" not in attrs:
            problems["address"] = [errors.coded(api_errors.REQUIRED, ADDRESS_REQUIRED_MESSAGE)]
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

    The address is optional. ``additional_details`` is stored on the witness
    row. Whether the caller is an active party of the case is checked when
    saving.
    """

    called_by_participant_id = serializers.UUIDField()
    what_will_witness_prove = serializers.CharField()


class PoaHolderCreateSerializer(IndividualPartySerializer):
    """Body of POST /cases/{id}/poa-holders (spec 0021 §4.5).

    The address is required. One mandate is created per represented party;
    whether each is an active complainant or accused of the case is checked
    when saving.
    """

    represented_participant_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )

    def validate_represented_participant_ids(self, value):
        """Require each represented party once."""
        return _require_each_once(value)

    def validate(self, attrs):
        """Require the address."""
        attrs = super().validate(attrs)
        if "address" not in attrs:
            raise api_errors.REQUIRED.validation_error({"address": [ADDRESS_REQUIRED_MESSAGE]})
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
    """A representation, with the advocate's name."""

    representation_id = serializers.UUIDField(source="id", read_only=True)
    advocate_name = serializers.CharField(source="advocate.name", read_only=True)
    client_participant_id = serializers.UUIDField(source="case_participant_id", read_only=True)

    class Meta:
        """Meta options."""

        model = Representation
        fields = [
            "representation_id",
            "case_id",
            "advocate_id",
            "advocate_name",
            "client_participant_id",
            "is_active",
            "from_date",
            "to_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ParticipantUpdateSerializer(RejectUnknownFieldsMixin, serializers.Serializer):
    """Body of PATCH /case-participants/{id} (spec 0021 §4.1).

    Changes only the case's copy of the party's details; the person and
    institution rows are never changed. Any of the fields may be sent, and
    nothing else: the role, person and institution cannot change.
    """

    unknown_field_message = "This field cannot be changed."

    name_at_filing = serializers.CharField(max_length=256, required=False)
    phone_number_at_filing = serializers.CharField(max_length=20, required=False, allow_null=True)
    gender_at_filing = serializers.ChoiceField(
        choices=Gender.choices, required=False, allow_null=True
    )
    age_at_filing = serializers.IntegerField(
        min_value=0, max_value=MAX_AGE, required=False, allow_null=True
    )
    designation_at_filing = serializers.CharField(max_length=128, required=False, allow_null=True)
    email_at_filing = serializers.EmailField(max_length=256, required=False, allow_null=True)
    # Institutions only. For an institution with no person acting for it,
    # ``name_at_filing`` and ``entity_name_at_filing`` are kept the same.
    entity_name_at_filing = serializers.CharField(max_length=256, required=False)
    address = AddressInputSerializer(required=False)
    is_party_in_person = serializers.BooleanField(required=False)
    # Complainants only; ``null`` clears it.
    party_in_person_affidavit = serializers.CharField(required=False, allow_null=True)
    additional_details = serializers.DictField(required=False)
    # Witnesses only (spec 0021 §4.3); they change the witness row.
    called_by_participant_id = serializers.UUIDField(required=False)
    what_will_witness_prove = serializers.CharField(required=False)

    def validate_party_in_person_affidavit(self, value):
        """Refuse editor output with no text in it; ``null`` clears it."""
        return _require_visible_text(value)

    def validate(self, attrs):
        """Require at least one change."""
        attrs = super().validate(attrs)
        if not attrs:
            raise api_errors.REQUIRED.validation_error("Send at least one field to change.")
        return attrs


class WitnessSerializer(serializers.ModelSerializer):
    """What only a witness has (spec 0020 §4.5)."""

    class Meta:
        """Meta options."""

        model = Witness
        fields = ["called_by_participant_id", "what_will_witness_prove", "additional_details"]
        read_only_fields = fields


class CaseParticipantSerializer(serializers.ModelSerializer):
    """A case participant: the case's copy of a party's details.

    Only ids of the person and institution are shown, never their stored
    details, which may have been entered by the other side (spec 0020 §3.4).
    ``witness`` is null for every role but a witness.
    """

    case_participant_id = serializers.UUIDField(source="id", read_only=True)
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
            "phone_number_at_filing",
            "gender_at_filing",
            "age_at_filing",
            "designation_at_filing",
            "email_at_filing",
            "entity_name_at_filing",
            "address_id",
            "is_party_in_person",
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


class AddressSerializer(serializers.ModelSerializer):
    """An address, as recorded for a participant on the case."""

    address_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        """Meta options."""

        model = Address
        fields = ["address_id", "line1", "city", "district", "state", "pincode", "police_station"]
        read_only_fields = fields


class PreviewParticipantSerializer(CaseParticipantSerializer):
    """A participant with their address on the case written out."""

    address = AddressSerializer(read_only=True, allow_null=True)

    class Meta(CaseParticipantSerializer.Meta):
        """Meta options."""

        fields = [*CaseParticipantSerializer.Meta.fields, "address"]
        read_only_fields = fields


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
