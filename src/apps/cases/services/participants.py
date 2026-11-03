"""Case parties: complainants, accused, witnesses, advocates and POA holders (spec 0021 §4).

A party write resolves the person and institution (``apps.parties.services``),
stores the address for service of notice, and records the case's own copy of
the party's details on a ``CaseParticipant``. Every row one write touches is
saved in one transaction, and the case row is locked for it, so ordinals are
assigned and renumbered one write at a time.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.address.models import Address
from apps.api import errors as api_errors
from apps.parties.models import contact_number_validator, phone_number_validator
from apps.parties.services import (
    create_asserted_person,
    get_or_create_institution,
    get_or_create_self_person,
)
from apps.users.models import AdvocateProfile

from .. import errors, models
from ..models import (
    COMPLAINANT_ONLY_MESSAGE,
    DESIGNATION_NOT_ALLOWED_MESSAGE,
    INSTITUTION_DETAILS_NOT_ALLOWED_MESSAGE,
    INSTITUTION_NAMES_DIFFER_MESSAGE,
    INSTITUTION_ROLES,
    CaseParticipant,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
    police_station_error,
)
from .services import (
    deactivate,
    editing,
    editing_or_creating,
    ensure_editable,
    errors_under,
    get_active_case_item,
    get_case_type,
    next_ordinal,
    unlink,
    validated_save,
)

# A mandate's model fields, by the names the API gives them, for a mandate
# created with its POA holder.
MANDATE_FIELD_NAMES = {"represented_participant": "represented_participant_ids"}
# Likewise for a representation created for its advocate.
REPRESENTATION_FIELD_NAMES = {"case_participant": "client_participant_ids"}

# The parties whose person row records a permanent address (an individual only).
PERMANENT_ADDRESS_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.POA_HOLDER)

INSTITUTION_SWITCH_MESSAGE = (
    "Only for an institution. To switch between an individual and an institution, "
    "remove the participant and add it again."
)


def _save_address(fields, user, field="address"):
    """Return the stored address for ``fields``, reusing an identical row; ``None`` if none.

    Errors are reported under ``field``, the name the request sent it as.
    """
    if fields is None:
        return None
    with errors_under(field):
        address, _ = Address.objects.get_or_create_address(created_by=user, **fields)
    return address


def add_participant(case_or_draft_id, user, role, data):
    """Add a party in ``role``, creating the case on first save.

    ``data`` is a validated ``ParticipantCreateSerializer`` body. The filer's
    own person (``is_self``) is reused unchanged; anyone else named is a new
    person. A person newly created for the party gets the address as their
    correspondence address, and a new institution gets it as its registered
    office.
    """
    # Raises 404 or 409 before anything is written.
    get_case_type(case_or_draft_id, user)
    with editing_or_creating(case_or_draft_id, user) as case:
        participant = _create_participant(case, user, role, data)
    return participant


def add_witness(case_or_draft_id, user, data):
    """Add a witness, creating the case on first save (spec 0021 §4.3).

    ``data`` is a validated ``WitnessCreateSerializer`` body. The participant
    is created as for any party, and a ``Witness`` row records which side
    calls them, what they will prove and the body's ``additional_details``.
    """
    get_case_type(case_or_draft_id, user)
    with editing_or_creating(case_or_draft_id, user) as case:
        participant = _create_participant(
            case,
            user,
            ParticipantRole.WITNESS,
            {**data, "is_party_in_person": False, "additional_details": {}},
        )
        witness = Witness(
            case_participant=participant,
            side=data["side"],
            what_will_witness_prove=data.get("what_will_witness_prove", ""),
            additional_details=data["additional_details"],
            created_by=user,
            updated_by=user,
        )
        validated_save(witness)
    return participant


def add_poa_holder(case_or_draft_id, user, data):
    """Add a POA holder and one mandate per party they act for (spec 0021 §4.5).

    ``data`` is a validated ``PoaHolderCreateSerializer`` body. The holder is
    a new participant even when the filer is already a party of the case.
    Returns the holder and the new mandates.
    """
    get_case_type(case_or_draft_id, user)
    with editing_or_creating(case_or_draft_id, user) as case:
        represented = _get_represented(case, data, "represented_participant_ids")
        holder = _create_participant(
            case, user, ParticipantRole.POA_HOLDER, {**data, "is_party_in_person": False}
        )
        mandates = []
        for party in represented:
            mandate = PoaMandate(
                case=case,
                poa_participant=holder,
                represented_participant=party,
                created_by=user,
                updated_by=user,
            )
            validated_save(mandate, renamed=MANDATE_FIELD_NAMES)
            mandates.append(mandate)
    return holder, mandates


def _get_represented(case, data, field):
    """Return the active participants of ``case`` listed in ``data[field]``, in the order given.

    ``PoaMandate.clean`` and ``Representation.clean`` check their roles and
    the rest.
    """
    case_participant_ids = data[field]
    found = CaseParticipant.objects.active().filter(case=case).in_bulk(case_participant_ids)
    if len(found) != len(case_participant_ids):
        raise errors.PARTICIPANT_NOT_ON_CASE.validation_error(
            {field: ["Must be active participants of the same case."]}
        )
    return [found[pk] for pk in case_participant_ids]


def get_mandate(poa_mandate_id, user):
    """Return an active mandate on one of ``user``'s cases, or raise ``NotFound``."""
    return get_active_case_item(PoaMandate, poa_mandate_id, user)


def revoke_mandate(mandate, user):
    """Revoke a mandate (soft delete); a holder left acting for no one is removed too."""
    ensure_editable(mandate.case)
    with editing(mandate.case, user):
        now = timezone.now()
        deactivate(mandate, user, revoked_at=now)
        holder = mandate.poa_participant
        if not holder.poa_mandates_held.active().exists():
            _remove(holder, user, now)


def add_advocate(case_or_draft_id, user, data):
    """Add an advocate for one or more clients, one representation each (spec 0021 §4.4).

    ``data`` is a validated ``AdvocateCreateSerializer`` body. Returns the new
    representations.
    """
    get_case_type(case_or_draft_id, user)
    advocate = AdvocateProfile.objects.filter(pk=data["advocate_id"]).first()
    if advocate is None:
        raise api_errors.DOES_NOT_EXIST.validation_error({"advocate_id": ["Advocate not found."]})
    with editing_or_creating(case_or_draft_id, user) as case:
        clients = _get_represented(case, data, "client_participant_ids")
        representations = []
        for client in clients:
            representation = Representation(
                case=case,
                advocate=advocate,
                case_participant=client,
                created_by=user,
                updated_by=user,
            )
            validated_save(representation, renamed=REPRESENTATION_FIELD_NAMES)
            representations.append(representation)
    return representations


def get_representation(representation_id, user):
    """Return an active representation on one of ``user``'s cases, or raise ``NotFound``."""
    return get_active_case_item(Representation, representation_id, user)


def end_representation(representation, user):
    """End a representation (soft delete); the row is kept as the record of who acted when."""
    ensure_editable(representation.case)
    with editing(representation.case, user):
        deactivate(representation, user, to_date=timezone.now())


def _create_participant(case, user, role, data):
    """Save a new participant in ``role`` on ``case``, within the caller's transaction."""
    address = _save_address(data.get("address"), user)

    institution = None
    if "institution" in data:
        with errors_under("institution"):
            institution = get_or_create_institution(
                user,
                data["institution"],
                address=address,
                require_identifier=role == ParticipantRole.COMPLAINANT,
            )

    # An individual complainant or POA holder has a permanent address: the
    # one sent when it differs from ``address``, else ``address`` itself.
    permanent_address = None
    if role in PERMANENT_ADDRESS_ROLES and institution is None:
        permanent_address = _save_address(data.get("permanent_address"), user, "permanent_address")
        permanent_address = permanent_address or address

    person = None
    if data["is_self"]:
        with errors_under("self"):
            person = get_or_create_self_person(user)
        if permanent_address is not None and person.permanent_address_id != permanent_address.pk:
            # The one change a filing makes to the filer's own person row: the
            # permanent address they just gave (spec 0020 §2.5).
            person.permanent_address = permanent_address
            person.updated_by = user
            person.save(update_fields=["permanent_address", "updated_by", "updated_at"])
    elif "person" in data:
        with errors_under("person"):
            person = create_asserted_person(
                user,
                data["person"],
                institution=institution,
                designation=data.get("designation"),
                address=address,
                permanent_address=permanent_address,
            )

    participant = CaseParticipant(
        case=case,
        person=person,
        institution=institution,
        role=role,
        ordinal=next_ordinal(CaseParticipant.objects.active().filter(case=case, role=role)),
        address=address,
        is_party_in_person=data["is_party_in_person"],
        # Yes unless the filer says otherwise; recorded for an accused only.
        resides_within_jurisdiction=data.get(
            "resides_within_jurisdiction", True if role == ParticipantRole.ACCUSED else None
        ),
        party_in_person_affidavit=data.get("party_in_person_affidavit"),
        contact_details_unknown_declared=data.get("contact_details_unknown_declared", False),
        additional_details=data["additional_details"],
        created_by=user,
        updated_by=user,
        **_snapshot(person, data),
    )
    validated_save(participant)
    return participant


def _snapshot(person, data):
    """Return the ``*_at_filing`` values for a new participant.

    Taken from the person when there is one. An institution is recorded by the
    name, number and email the filer entered, not those stored for a reused
    institution, which the filer is never shown.
    """
    institution = data.get("institution")
    snapshot = {}
    if institution is not None:
        snapshot = {"entity_name_at_filing": institution["entity_name"].strip()}
    if person is not None:
        return {
            **snapshot,
            "name_at_filing": person.name,
            "phone_number_at_filing": person.phone_number,
            "email_at_filing": person.email_address,
            "gender_at_filing": person.gender,
            "age_at_filing": person.current_age,
            "designation_at_filing": data.get("designation"),
        }
    return {
        **snapshot,
        "name_at_filing": snapshot["entity_name_at_filing"],
        "phone_number_at_filing": institution.get("contact_number") or None,
        "email_at_filing": institution.get("email_address") or None,
    }


def get_participant(case_participant_id, user):
    """Return an active participant on one of ``user``'s cases, or raise ``NotFound``."""
    return get_active_case_item(CaseParticipant, case_participant_id, user)


def update_participant(participant, user, data):
    """Change the case's copy of a party's details; the person and institution are untouched.

    ``data`` is a validated ``ParticipantUpdateSerializer`` body. A new address
    is stored as its own row and the participant repointed; the old row stays.
    A witness's side, statement and ``additional_details`` are on its
    ``Witness`` row. Accused and witness addresses need a police station.
    ``institution`` re-links an institution participant (``_relink_institution``);
    switching between an individual and an institution is a remove and re-add.
    """
    ensure_editable(participant.case)
    data = dict(data)
    institution_fields = data.pop("institution", None)
    is_witness = participant.role == ParticipantRole.WITNESS
    witness_fields = {
        field: data.pop(field) for field in ("side", "what_will_witness_prove") if field in data
    }
    if is_witness and "additional_details" in data:
        witness_fields["additional_details"] = data.pop("additional_details")
    problems = {}
    if not is_witness:
        problems.update(
            {
                field: [errors.coded(errors.FIELD_NOT_APPLICABLE, "Only for a witness.")]
                for field in witness_fields
            }
        )
    if participant.role not in INSTITUTION_ROLES and "is_party_in_person" in data:
        problems["is_party_in_person"] = [
            errors.coded(errors.FIELD_NOT_APPLICABLE, "Only for a complainant or an accused.")
        ]
    for field in ("resides_within_jurisdiction", "contact_details_unknown_declared"):
        if participant.role != ParticipantRole.ACCUSED and field in data:
            problems[field] = [errors.coded(errors.FIELD_NOT_APPLICABLE, "Only for an accused.")]
    if participant.role != ParticipantRole.COMPLAINANT and "party_in_person_affidavit" in data:
        problems["party_in_person_affidavit"] = [
            errors.coded(errors.FIELD_NOT_APPLICABLE, COMPLAINANT_ONLY_MESSAGE)
        ]
    if data.get("is_party_in_person") and participant.representations.active().exists():
        problems["is_party_in_person"] = [
            errors.coded(errors.PARTY_IN_PERSON, models.PARTY_HAS_ADVOCATES_MESSAGE)
        ]
    if "designation_at_filing" in data and not (
        is_witness or (participant.person_id and participant.institution_id)
    ):
        problems["designation_at_filing"] = [
            errors.coded(errors.FIELD_NOT_APPLICABLE, DESIGNATION_NOT_ALLOWED_MESSAGE)
        ]
    if institution_fields is not None and not participant.institution_id:
        problems["institution"] = [
            errors.coded(errors.FIELD_NOT_APPLICABLE, INSTITUTION_SWITCH_MESSAGE)
        ]
    if problem := police_station_error(participant.role, data.get("address")):
        problems["address"] = problem
    if not participant.institution_id:
        if "entity_name_at_filing" in data:
            problems["entity_name_at_filing"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, INSTITUTION_DETAILS_NOT_ALLOWED_MESSAGE)
            ]
    elif not participant.person_id:
        # An institution alone is named by the institution's name, so the two
        # stay the same: one sent sets both, and both sent must agree.
        if "name_at_filing" in data and "entity_name_at_filing" in data:
            if data["name_at_filing"] != data["entity_name_at_filing"]:
                problems["entity_name_at_filing"] = [
                    errors.coded(api_errors.INVALID, INSTITUTION_NAMES_DIFFER_MESSAGE)
                ]
        elif "name_at_filing" in data:
            data["entity_name_at_filing"] = data["name_at_filing"]
        elif "entity_name_at_filing" in data:
            data["name_at_filing"] = data["entity_name_at_filing"]
    if data.get("phone_number_at_filing"):
        # A person's number is a mobile in E.164; an institution's may be a landline.
        validator = phone_number_validator if participant.person_id else contact_number_validator
        try:
            validator(data["phone_number_at_filing"])
        except DjangoValidationError as exc:
            problems["phone_number_at_filing"] = exc.messages
    if problems:
        raise serializers.ValidationError(problems)

    with editing(participant.case, user):
        # Read again under the case lock: a concurrent removal is not undone.
        participant = get_participant(participant.pk, user)
        if "address" in data:
            participant.address = _save_address(data.pop("address"), user)
        if institution_fields is not None:
            _relink_institution(participant, user, institution_fields, data)
        for field, value in data.items():
            setattr(participant, field, value)
        participant.updated_by = user
        validated_save(participant)
        if witness_fields:
            _update_witness(participant, user, witness_fields)
    return participant


def _relink_institution(participant, user, fields, data):
    """Point ``participant`` at the institution ``fields`` names, resolved as on create.

    An existing institution with the PAN or CIN is linked, otherwise a new one
    is created with the participant's address as its registered office.
    Neither the old nor the matched institution is changed, and nor is the
    person acting for it: other cases may share them. The participant keeps
    its id, so its advocates, mandates and documents stay linked.

    An institution alone is shown by the name and number sent, as on create,
    unless the same request sets ``name_at_filing`` or ``phone_number_at_filing``.
    """
    with errors_under("institution"):
        participant.institution = get_or_create_institution(
            user,
            fields,
            address=participant.address,
            require_identifier=participant.role == ParticipantRole.COMPLAINANT,
        )
    if participant.person_id is None:
        for field, value in _snapshot(None, {"institution": fields}).items():
            data.setdefault(field, value)


def _update_witness(participant, user, fields):
    """Apply ``fields``, by the API's names, to the participant's ``Witness`` row."""
    witness = participant.witness
    for field, value in fields.items():
        setattr(witness, field, value)
    witness.updated_by = user
    validated_save(witness)


def remove_participant(participant, user):
    """Remove a party from its case (soft delete) and end what depended on them.

    The remaining participants of the role are renumbered 1…n. The party's
    representations end, and every mandate they hold or are represented by is
    revoked; a POA holder left with no active mandate is removed in turn, as
    they no longer act for anyone.
    """
    ensure_editable(participant.case)
    with editing(participant.case, user):
        # Read again under the case lock, so a second removal finds nothing.
        _remove(get_participant(participant.pk, user), user, timezone.now())


def _remove(participant, user, now):
    """Remove ``participant`` and end what depended on them, within the caller's transaction.

    Documents linked to them (an identity proof, a vakalatnama) stay on the
    case, unlinked, as when a document's evidence is removed.
    """
    deactivate(participant, user, end_date=now)
    _renumber(participant.case_id, participant.role, user)
    unlink(participant.documents.active(), "case_participant", user)

    for representation in participant.representations.active():
        deactivate(representation, user, to_date=now)

    holders = {}
    mandates = PoaMandate.objects.active().filter(
        Q(poa_participant=participant) | Q(represented_participant=participant)
    )
    for mandate in mandates.select_related("poa_participant"):
        deactivate(mandate, user, revoked_at=now)
        if mandate.poa_participant_id != participant.pk:
            holders[mandate.poa_participant_id] = mandate.poa_participant
    for holder in holders.values():
        if holder.is_active and not holder.poa_mandates_held.active().exists():
            _remove(holder, user, now)


def _renumber(case_id, role, user):
    """Number the active participants of ``role`` 1…n, keeping their order.

    Ascending order means each target ordinal is already free, so the
    unique-active-ordinal constraint holds after every single update.
    """
    remaining = CaseParticipant.objects.active().filter(case_id=case_id, role=role)
    for ordinal, other in enumerate(remaining.order_by("ordinal"), start=1):
        if other.ordinal != ordinal:
            other.ordinal = ordinal
            other.updated_by = user
            other.save(update_fields=["ordinal", "updated_by", "updated_at"])
