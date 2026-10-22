"""Case parties: complainants, accused and witnesses (spec 0021 §4.1–§4.3).

A party write resolves the person and institution (``apps.parties.services``),
stores the address for service of notice, and records the case's own copy of
the party's details on a ``CaseParticipant``. Every row one write touches is
saved in one transaction, and the case row is locked for it, so ordinals are
assigned and renumbered one write at a time.
"""

from contextlib import contextmanager

from django.core.exceptions import NON_FIELD_ERRORS
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.address.models import Address
from apps.parties.models import contact_number_validator, phone_number_validator
from apps.parties.services import (
    create_asserted_person,
    get_or_create_institution,
    get_or_create_self_person,
)

from ..models import Case, CaseParticipant, ParticipantRole, PoaMandate, Witness
from .services import (
    deactivate,
    ensure_editable,
    get_active_case_item,
    get_case_type,
    get_or_create_case,
    touch,
)

# A witness's model fields, by the names the API gives them.
WITNESS_FIELD_NAMES = {"called_by_participant": "called_by_participant_id"}


@contextmanager
def _errors_under(field=None, *, as_whole=False, renamed=None):
    """Turn a model ``ValidationError`` into a 400, nested under ``field`` when given.

    ``as_whole`` reports every message as a non-field error, for a request
    with no body (a DELETE), where the model's field names would mean nothing.
    ``renamed`` maps model field names to the request's.
    """
    renamed = {NON_FIELD_ERRORS: api_settings.NON_FIELD_ERRORS_KEY, **(renamed or {})}
    try:
        yield
    except DjangoValidationError as exc:
        if hasattr(exc, "error_dict") and not as_whole:
            detail = {renamed.get(key, key): messages for key, messages in exc.message_dict.items()}
        else:
            detail = {api_settings.NON_FIELD_ERRORS_KEY: exc.messages}
        raise serializers.ValidationError({field: detail} if field else detail) from exc


def _lock(case):
    """Lock the case row until the transaction ends, serialising its party writes."""
    Case.objects.select_for_update().filter(pk=case.pk).first()


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
    with transaction.atomic():
        case = get_or_create_case(case_or_draft_id, user)
        _lock(case)
        participant = _create_participant(case, user, role, data)
        touch(case, user)
    return participant


def add_witness(case_or_draft_id, user, data):
    """Add a witness, creating the case on first save (spec 0021 §4.3).

    ``data`` is a validated ``WitnessCreateSerializer`` body. The participant
    is created as for any party, and a ``Witness`` row records who calls
    them, what they will prove and the body's ``additional_details``.
    """
    get_case_type(case_or_draft_id, user)
    with transaction.atomic():
        case = get_or_create_case(case_or_draft_id, user)
        _lock(case)
        participant = _create_participant(
            case, user, ParticipantRole.WITNESS, {**data, "additional_details": {}}
        )
        witness = Witness(
            case_participant=participant,
            called_by_participant=_get_caller(case, data["called_by_participant_id"]),
            what_will_witness_prove=data["what_will_witness_prove"],
            additional_details=data["additional_details"],
            created_by=user,
            updated_by=user,
        )
        with _errors_under(renamed=WITNESS_FIELD_NAMES):
            witness.full_clean()
        witness.save()
        touch(case, user)
    return participant


def _get_caller(case, case_participant_id):
    """Return the participant of ``case`` calling a witness; ``Witness.clean`` checks the rest."""
    caller = CaseParticipant.objects.filter(pk=case_participant_id, case=case).first()
    if caller is None:
        raise serializers.ValidationError(
            {"called_by_participant_id": ["Must be a participant of the same case."]}
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
        ordinal=_next_ordinal(case, role),
        address=address,
        is_party_in_person=data["is_party_in_person"],
        additional_details=data["additional_details"],
        created_by=user,
        updated_by=user,
        **_snapshot(person, data),
    )
    with _errors_under():
        participant.full_clean()
    participant.save()
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


def _next_ordinal(case, role):
    last = (
        CaseParticipant.objects.active()
        .filter(case=case, role=role)
        .aggregate(last=Max("ordinal"))["last"]
    )
    return (last or 0) + 1


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
    errors = {}
    if not is_witness:
        errors.update({field: ["Only for a witness."] for field in witness_fields})
    elif "is_party_in_person" in data:
        errors["is_party_in_person"] = ["Only for a complainant or an accused."]
    if data.get("is_party_in_person") and participant.representations.active().exists():
        errors["is_party_in_person"] = ["Remove this party's advocates first."]
    if "designation_at_filing" in data and not (
        participant.person_id and participant.institution_id
    ):
        errors["designation_at_filing"] = ["Only for a person acting for an institution."]
    if data.get("phone_number_at_filing"):
        # A person's number is a mobile in E.164; an institution's may be a landline.
        validator = phone_number_validator if participant.person_id else contact_number_validator
        try:
            validator(data["phone_number_at_filing"])
        except DjangoValidationError as exc:
            errors["phone_number_at_filing"] = exc.messages
    if errors:
        raise serializers.ValidationError(errors)

    with transaction.atomic():
        _lock(participant.case)
        if "address" in data:
            participant.address = _save_address(data.pop("address"), user)
        for field, value in data.items():
            setattr(participant, field, value)
        participant.updated_by = user
        with _errors_under():
            participant.full_clean()
        participant.save()
        if witness_fields:
            _update_witness(participant, user, witness_fields)
        touch(participant.case, user)
    return participant


def _update_witness(participant, user, fields):
    witness = participant.witness
    if "called_by_participant_id" in fields:
        witness.called_by_participant = _get_caller(
            participant.case, fields.pop("called_by_participant_id")
        )
    for field, value in fields.items():
        setattr(witness, field, value)
    witness.updated_by = user
    with _errors_under(renamed=WITNESS_FIELD_NAMES):
        witness.full_clean()
    witness.save()


def remove_participant(participant, user):
    """Remove a party from its case (soft delete) and end what depended on them.

    The remaining participants of the role are renumbered 1…n. The party's
    representations end, and every mandate they hold or are represented by is
    revoked; a POA holder left with no active mandate is removed in turn, as
    they no longer act for anyone. Refused while an active witness names the
    party as its caller.
    """
    ensure_editable(participant.case)
    with transaction.atomic():
        _lock(participant.case)
        _remove(participant, user, timezone.now())
        touch(participant.case, user)


def _remove(participant, user, now):
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
