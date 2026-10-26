"""Case parties: complainants, accused, witnesses, advocates and POA holders (spec 0021 §4).

A party write resolves the person and institution (``apps.parties.services``),
stores the address for service of notice, and records the case's own copy of
the party's details on a ``CaseParticipant``. Every row one write touches is
saved in one transaction, and the case row is locked for it, so ordinals are
assigned and renumbered one write at a time.
"""

from contextlib import contextmanager

from django.core.exceptions import NON_FIELD_ERRORS
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.fields import get_error_detail
from rest_framework.settings import api_settings

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
    DESIGNATION_NOT_ALLOWED_MESSAGE,
    INSTITUTION_ROLES,
    CaseParticipant,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
)
from .services import (
    deactivate,
    editing,
    editing_or_creating,
    ensure_editable,
    get_active_case_item,
    get_case_type,
    next_ordinal,
)

# A witness's model fields, by the names the API gives them.
WITNESS_FIELD_NAMES = {"called_by_participant": "called_by_participant_id"}
# Likewise for a mandate created with its POA holder.
MANDATE_FIELD_NAMES = {"represented_participant": "represented_participant_ids"}
# Likewise for a representation created for its advocate.
REPRESENTATION_FIELD_NAMES = {"case_participant": "client_participant_ids"}


@contextmanager
def _errors_under(field=None, *, as_whole=False, renamed=None):
    """Turn a model ``ValidationError`` into a 400, nested under ``field`` when given.

    Every message keeps the code the model gave it: a case rule's API code, or
    Django's own. ``as_whole`` reports every message as a non-field error, for
    a request with no body (a DELETE), where the model's field names would mean
    nothing. ``renamed`` maps model field names to the request's.
    """
    renamed = {NON_FIELD_ERRORS: api_settings.NON_FIELD_ERRORS_KEY, **(renamed or {})}
    try:
        yield
    except DjangoValidationError as exc:
        detail = get_error_detail(exc)
        if isinstance(detail, dict) and not as_whole:
            detail = {renamed.get(key, key): messages for key, messages in detail.items()}
        else:
            if isinstance(detail, dict):
                detail = [message for messages in detail.values() for message in messages]
            detail = {api_settings.NON_FIELD_ERRORS_KEY: detail}
        raise serializers.ValidationError({field: detail} if field else detail) from exc


def _validated_save(row, **errors_under):
    """Save ``row`` once ``full_clean`` passes; its errors become a 400 as in ``_errors_under``."""
    with _errors_under(**errors_under):
        row.full_clean()
    row.save()


def _save_address(fields, user):
    """Return the stored address for ``fields``, reusing an identical row; ``None`` if none."""
    if fields is None:
        return None
    with _errors_under("address"):
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
    is created as for any party, and a ``Witness`` row records who calls
    them, what they will prove and the body's ``additional_details``.
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
            called_by_participant=_get_caller(case, data["called_by_participant_id"]),
            what_will_witness_prove=data["what_will_witness_prove"],
            additional_details=data["additional_details"],
            created_by=user,
            updated_by=user,
        )
        _validated_save(witness, renamed=WITNESS_FIELD_NAMES)
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
            _validated_save(mandate, renamed=MANDATE_FIELD_NAMES)
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
            _validated_save(representation, renamed=REPRESENTATION_FIELD_NAMES)
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


def _get_caller(case, case_participant_id):
    """Return the participant of ``case`` calling a witness; ``Witness.clean`` checks the rest."""
    caller = CaseParticipant.objects.filter(pk=case_participant_id, case=case).first()
    if caller is None:
        raise errors.PARTICIPANT_NOT_ON_CASE.validation_error(
            {"called_by_participant_id": [errors.PARTICIPANT_NOT_ON_CASE.message]}
        )
    return caller


def _create_participant(case, user, role, data):
    """Save a new participant in ``role`` on ``case``, within the caller's transaction."""
    address = _save_address(data.get("address"), user)

    institution = None
    if "institution" in data:
        with _errors_under("institution"):
            institution = get_or_create_institution(user, data["institution"], address=address)

    person = None
    if data["is_self"]:
        with _errors_under("self"):
            person = get_or_create_self_person(user)
    elif "person" in data:
        with _errors_under("person"):
            person = create_asserted_person(
                user,
                data["person"],
                institution=institution,
                designation=data.get("designation"),
                address=address,
            )

    participant = CaseParticipant(
        case=case,
        person=person,
        institution=institution,
        role=role,
        ordinal=next_ordinal(CaseParticipant.objects.active().filter(case=case, role=role)),
        address=address,
        is_party_in_person=data["is_party_in_person"],
        additional_details=data["additional_details"],
        created_by=user,
        updated_by=user,
        **_snapshot(person, data),
    )
    _validated_save(participant)
    return participant


def _snapshot(person, data):
    """Return the ``*_at_filing`` values for a new participant.

    Taken from the person when there is one. An institution alone is shown by
    the name and number the filer entered, not those stored for a reused
    institution, which the filer is never shown.
    """
    if person is not None:
        return {
            "name_at_filing": person.name,
            "phone_number_at_filing": person.phone_number,
            "gender_at_filing": person.gender,
            "age_at_filing": person.current_age,
            "designation_at_filing": data.get("designation"),
        }
    institution = data["institution"]
    return {
        "name_at_filing": institution["entity_name"].strip(),
        "phone_number_at_filing": institution.get("contact_number") or None,
    }


def get_participant(case_participant_id, user):
    """Return an active participant on one of ``user``'s cases, or raise ``NotFound``."""
    return get_active_case_item(CaseParticipant, case_participant_id, user)


def update_participant(participant, user, data):
    """Change the case's copy of a party's details; the person and institution are untouched.

    ``data`` is a validated ``ParticipantUpdateSerializer`` body. A new address
    is stored as its own row and the participant repointed; the old row stays.
    A witness's caller, statement and ``additional_details`` are on its
    ``Witness`` row.
    """
    ensure_editable(participant.case)
    data = dict(data)
    is_witness = participant.role == ParticipantRole.WITNESS
    witness_fields = {
        field: data.pop(field)
        for field in ("called_by_participant_id", "what_will_witness_prove")
        if field in data
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
    if data.get("is_party_in_person") and participant.representations.active().exists():
        problems["is_party_in_person"] = [
            errors.coded(errors.PARTY_IN_PERSON, models.PARTY_HAS_ADVOCATES_MESSAGE)
        ]
    if "designation_at_filing" in data and not (
        participant.person_id and participant.institution_id
    ):
        problems["designation_at_filing"] = [
            errors.coded(errors.FIELD_NOT_APPLICABLE, DESIGNATION_NOT_ALLOWED_MESSAGE)
        ]
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
        if "address" in data:
            participant.address = _save_address(data.pop("address"), user)
        for field, value in data.items():
            setattr(participant, field, value)
        participant.updated_by = user
        _validated_save(participant)
        if witness_fields:
            _update_witness(participant, user, witness_fields)
    return participant


def _update_witness(participant, user, fields):
    """Apply ``fields``, by the API's names, to the participant's ``Witness`` row."""
    witness = participant.witness
    if "called_by_participant_id" in fields:
        witness.called_by_participant = _get_caller(
            participant.case, fields.pop("called_by_participant_id")
        )
    for field, value in fields.items():
        setattr(witness, field, value)
    witness.updated_by = user
    _validated_save(witness, renamed=WITNESS_FIELD_NAMES)


def remove_participant(participant, user):
    """Remove a party from its case (soft delete) and end what depended on them.

    The remaining participants of the role are renumbered 1…n. The party's
    representations end, and every mandate they hold or are represented by is
    revoked; a POA holder left with no active mandate is removed in turn, as
    they no longer act for anyone. Refused while an active witness names the
    party as its caller.
    """
    ensure_editable(participant.case)
    with editing(participant.case, user):
        _remove(participant, user, timezone.now())


def _remove(participant, user, now):
    """Remove ``participant`` and end what depended on them, within the caller's transaction."""
    # clean() holds the removal rules, so it is run on the row as removed.
    participant.is_active = False
    with _errors_under(as_whole=True):
        participant.full_clean()
    deactivate(participant, user, end_date=now)
    _renumber(participant.case_id, participant.role, user)

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
