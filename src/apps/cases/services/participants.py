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
from apps.parties.models import normalize_identifier, pan_cin_errors
from apps.parties.services import (
    create_asserted_person,
    get_or_create_institution,
    get_or_create_self_person,
)
from apps.users.models import AdvocateProfile

from .. import errors, models
from ..models import (
    ADDRESS_REQUIRED_MESSAGE,
    COMPLAINANT_ONLY_MESSAGE,
    DESIGNATION_NOT_ALLOWED_MESSAGE,
    INSTITUTION_CONTACTS_MESSAGE,
    INSTITUTION_DETAILS_NOT_ALLOWED_MESSAGE,
    INSTITUTION_NAMES_DIFFER_MESSAGE,
    INSTITUTION_ROLES,
    PERMANENT_ADDRESS_MESSAGE,
    PERSON_OF_ANOTHER_USER_MESSAGE,
    PERSON_ONLY_MESSAGE,
    CaseParticipant,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
    police_station_problems,
)
from .contacts import (
    CONTACT_LISTS,
    contacts_of,
    move_institution_contacts,
    replace_contacts,
    save_addresses,
)
from .services import (
    clear_preview_cache,
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

INSTITUTION_ONLY_MESSAGE = "Only for an institution."
INSTITUTION_CONTACTS_TWICE_MESSAGE = (
    "Send each of the institution's contact lists once, here or under institution."
)
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
    person, who keeps their first mobile number, email and address. The
    contacts themselves are the case's (``contacts.replace_contacts``).
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
    """Save a new participant in ``role`` on ``case``, with its contacts, in the caller's transaction."""
    own_lists = {field: data[field] for field in CONTACT_LISTS if field in data}
    addresses = save_addresses(own_lists.get("addresses", []), user, ("addresses",))
    address = addresses[0] if addresses else None

    institution = None
    institution_lists = {}
    # Another representative of an institution already accused on the case.
    represented = (
        _accused_institution(case, data["institution_id"]) if "institution_id" in data else None
    )
    if represented is not None:
        institution = represented.institution
    elif "institution" in data:
        institution_fields = dict(data["institution"])
        institution_lists = {
            field: institution_fields.pop(field)
            for field in CONTACT_LISTS
            if field in institution_fields
        }
        with errors_under("institution"):
            institution = get_or_create_institution(
                user,
                institution_fields,
                require_identifier=role == ParticipantRole.COMPLAINANT,
            )

    # An individual complainant or POA holder has a permanent address: the
    # one sent when it differs from their first address, else that address.
    permanent_address = sent_permanent_address = None
    if role in PERMANENT_ADDRESS_ROLES and institution is None:
        sent_permanent_address = _save_address(
            data.get("permanent_address"), user, "permanent_address"
        )
        permanent_address = sent_permanent_address or address

    person = None
    if data["is_self"]:
        with errors_under("self"):
            person = get_or_create_self_person(user)
        # The filer's own person row takes the permanent address they just
        # gave (spec 0020 §2.5). Falling back to ``address`` only fills one
        # they lack; it never replaces theirs.
        if permanent_address is not None and (
            sent_permanent_address or person.permanent_address_id is None
        ):
            _change_person(person, user, permanent_address=permanent_address)
    elif "person" in data:
        with errors_under("person"):
            person = create_asserted_person(
                user,
                {
                    **data["person"],
                    "phone_number": next(iter(own_lists.get("mobile_numbers", [])), None),
                    "email_address": next(iter(own_lists.get("email_addresses", [])), None),
                },
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
    if represented is not None:
        # The case's name for the institution, as its other participants have it.
        participant.entity_name_at_filing = represented.entity_name_at_filing
    validated_save(participant)
    # The person acting for an institution carries it on their own contacts.
    replace_contacts(case, user, own_lists, participant=participant, institution=institution)
    if institution is not None:
        replace_contacts(
            case, user, institution_lists, institution=institution, path=("institution",)
        )
    return participant


def _accused_institution(case, institution_id):
    """Return an active accused participant of ``case`` that is ``institution_id``, or raise 400."""
    found = (
        CaseParticipant.objects.active()
        .filter(case=case, role=ParticipantRole.ACCUSED, institution_id=institution_id)
        .select_related("institution")
        .order_by("ordinal")
        .first()
    )
    if found is None:
        raise api_errors.DOES_NOT_EXIST.validation_error(
            {"institution_id": ["No institution with this id is accused on this case."]}
        )
    return found


def _snapshot(person, data):
    """Return the ``*_at_filing`` values for a new participant.

    Taken from the person when there is one. An institution is recorded by the
    name the filer entered, not the one stored for a reused institution.
    """
    institution = data.get("institution")
    snapshot = {}
    if institution is not None:
        snapshot = {"entity_name_at_filing": institution["entity_name"].strip()}
    if person is not None:
        return {
            **snapshot,
            "name_at_filing": person.name,
            "gender_at_filing": person.gender,
            "age_at_filing": person.current_age,
            "designation_at_filing": data.get("designation"),
        }
    return {
        **snapshot,
        "name_at_filing": snapshot["entity_name_at_filing"],
    }


def _may_change_person(participant, user):
    """Return whether ``user`` may change the participant's person row.

    Anyone filing the case may, until the person registers and claims the row;
    then only that user, an advocate actively representing the participant, or
    a filer who is themselves an active complainant on the case.
    """
    owner_id = participant.person.user_id
    return (
        owner_id in (None, user.pk)
        or participant.representations.active().filter(advocate__user=user).exists()
        or CaseParticipant.objects.active()
        .filter(case_id=participant.case_id, role=ParticipantRole.COMPLAINANT, person__user=user)
        .exists()
    )


def _change_person(person, user, **fields):
    """Set ``fields`` on the person row, saving only what differs.

    The person row holds current data, so a party write may change it; the
    participant's ``*_at_filing`` snapshot is what the case keeps. Every
    filing showing this person shows these fields, so each one's cached
    preview is dropped (spec 0021 §6.1).
    """
    changed = {field: value for field, value in fields.items() if getattr(person, field) != value}
    if not changed:
        return
    for field, value in changed.items():
        setattr(person, field, value)
    person.updated_by = user
    person.save(update_fields=[*changed, "updated_by", "updated_at"])
    for case_id in person.case_participations.values_list("case_id", flat=True).distinct():
        clear_preview_cache(case_id)


def get_participant(case_participant_id, user):
    """Return an active participant on one of ``user``'s cases, or raise ``NotFound``."""
    return get_active_case_item(CaseParticipant, case_participant_id, user)


def update_participant(participant, user, data):
    """Change the case's copy of a party's details, and an individual's permanent address.

    ``data`` is a validated ``ParticipantUpdateSerializer`` body. The
    ``*_at_filing`` snapshot is changed on the participant; the institution
    row never is. ``permanent_address`` (an individual complainant or POA
    holder) and ``disability_status`` (anyone with a person) are set on the
    person. ``permanent_address: null`` makes it the participant's first
    address again, as when none is sent on create, and is ignored for a party
    that has no permanent address. Once another user has claimed the person,
    only they or their advocate on this case may change it.
    ``mobile_numbers``, ``email_addresses`` and ``addresses`` each replace the
    participant's list; inside ``institution``, the institution's own in this
    case (``contacts.replace_contacts``). Accused and witness addresses need a
    police station. A witness's side, statement and ``additional_details``
    are on its ``Witness`` row.
    ``institution`` re-links an institution participant (``_relink_institution``);
    switching between an individual and an institution is a remove and re-add.
    """
    ensure_editable(participant.case)
    data = dict(data)
    institution_fields = data.pop("institution", None)
    institution_lists = {}
    if institution_fields is not None:
        institution_fields = dict(institution_fields)
        institution_lists = {
            field: institution_fields.pop(field)
            for field in CONTACT_LISTS
            if field in institution_fields
        }
    # The institution's own lists, sent without re-linking it, or inside
    # ``institution``; reported under whichever field carried them.
    institution_contacts = data.pop("institution_contacts", None)
    institution_lists_field = "institution"
    sent_twice = set(institution_contacts or {}) & set(institution_lists)
    if institution_contacts is not None:
        institution_lists_field = "institution_contacts"
        institution_lists = {**institution_lists, **institution_contacts}
    own_lists = {field: data.pop(field) for field in CONTACT_LISTS if field in data}
    # Fields of the person row, not the participant.
    person_fields = {field: data.pop(field) for field in ("disability_status",) if field in data}
    sends_permanent_address = "permanent_address" in data
    permanent_address_fields = data.pop("permanent_address", None)
    has_permanent_address = (
        participant.role in PERMANENT_ADDRESS_ROLES
        and participant.person_id
        and not participant.institution_id
    )
    if sends_permanent_address and permanent_address_fields is None and not has_permanent_address:
        # Clearing what the party cannot have changes nothing.
        sends_permanent_address = False
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
    if institution_contacts is not None and not participant.institution_id:
        problems["institution_contacts"] = [
            errors.coded(errors.FIELD_NOT_APPLICABLE, INSTITUTION_ONLY_MESSAGE)
        ]
    elif sent_twice:
        problems["institution_contacts"] = [
            errors.coded(api_errors.INVALID, INSTITUTION_CONTACTS_TWICE_MESSAGE)
        ]
    problems.update(
        _contact_problems(participant, own_lists, institution_lists, data, institution_lists_field)
    )
    if person_fields:
        if not participant.person_id:
            problems["disability_status"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, PERSON_ONLY_MESSAGE)
            ]
        elif not _may_change_person(participant, user):
            problems["disability_status"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, PERSON_OF_ANOTHER_USER_MESSAGE)
            ]
    if sends_permanent_address:
        if not has_permanent_address:
            problems["permanent_address"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, PERMANENT_ADDRESS_MESSAGE)
            ]
        elif not _may_change_person(participant, user):
            problems["permanent_address"] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, PERSON_OF_ANOTHER_USER_MESSAGE)
            ]
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
    if problems:
        raise serializers.ValidationError(problems)

    with editing(participant.case, user):
        # Read again under the case lock: a concurrent removal is not undone.
        participant = get_participant(participant.pk, user)
        case = participant.case
        old_institution_id = participant.institution_id
        if institution_fields is not None:
            if _identified_by_nothing(participant.institution, institution_fields):
                _edit_institution(participant, user, institution_fields, data)
            else:
                _relink_institution(participant, user, institution_fields, data)
        for field, value in data.items():
            setattr(participant, field, value)
        participant.updated_by = user
        validated_save(participant)
        # Only once the participant's rules allow the new institution.
        if participant.institution_id != old_institution_id:
            move_institution_contacts(case, user, old_institution_id, participant.institution)
        if old_institution_id:
            _align_representatives(participant, user, old_institution_id)
        if participant.person_id:
            replace_contacts(
                case, user, own_lists, participant=participant, institution=participant.institution
            )
        if participant.institution_id:
            replace_contacts(
                case,
                user,
                institution_lists,
                institution=participant.institution,
                path=(institution_lists_field,),
            )
        if sends_permanent_address:
            # After the addresses change, since ``null`` falls back to the first.
            permanent_address = _save_address(permanent_address_fields, user, "permanent_address")
            person_fields["permanent_address"] = permanent_address or _first_address(participant)
        if person_fields:
            _change_person(participant.person, user, **person_fields)
        if witness_fields:
            _update_witness(participant, user, witness_fields)
    return participant


def _relink_institution(participant, user, fields, data):
    """Point ``participant`` at the institution ``fields`` names, resolved as on create.

    An existing institution with the PAN or CIN is linked, otherwise a new one
    is created. Neither the old nor the matched institution is changed, and
    nor is the person acting for it: other cases may share them. The
    participant keeps its id, so its advocates, mandates, documents and
    contacts stay linked.

    The institution's name is taken from the ``institution`` sent, as on
    create, unless the same request sets ``entity_name_at_filing`` or
    ``name_at_filing``. A person acting for the institution keeps their own
    name.
    """
    with errors_under("institution"):
        participant.institution = get_or_create_institution(
            user,
            fields,
            require_identifier=participant.role == ParticipantRole.COMPLAINANT,
        )
    _name_from(participant, fields, data)


def _identified_by_nothing(institution, fields):
    """Return whether neither ``institution`` nor ``fields`` has a PAN or CIN.

    Such an institution can never be matched by another filing, so it is this
    case's alone and may be edited in place.
    """
    return not any(
        (
            institution.pan,
            institution.cin,
            normalize_identifier(fields.get("pan")),
            normalize_identifier(fields.get("cin")),
        )
    )


def _edit_institution(participant, user, fields, data):
    """Change the participant's institution, one no other filing can share, in place.

    Its type, name and skip declaration become those sent, for every
    participant linked to it; it keeps its id. The name is the case's too,
    as on a re-link.
    """
    institution = participant.institution
    skip_declared = fields.get("pan_cin_skip_declared", False)
    required = participant.role == ParticipantRole.COMPLAINANT
    with errors_under("institution"):
        if problems := pan_cin_errors(None, None, skip_declared, required=required):
            raise DjangoValidationError(problems)
        institution.entity_type = fields["entity_type"]
        institution.entity_name = fields["entity_name"]
        institution.pan_cin_skip_declared = skip_declared
        institution.updated_by = user
        institution.save()
    _name_from(participant, fields, data)


def _name_from(participant, fields, data):
    """Name the participant after the institution sent, unless the request names it itself."""
    snapshot = _snapshot(None, {"institution": fields})
    if participant.person_id is not None:
        snapshot = {"entity_name_at_filing": snapshot["entity_name_at_filing"]}
    for field, value in snapshot.items():
        data.setdefault(field, value)


def _align_representatives(participant, user, old_institution_id):
    """Keep every participant of the participant's former institution in step with it.

    The others summoned for the same institution (spec 0020 §4.2) follow a
    re-link to the new institution, and take the case's name for it; one with
    no person is named after it too.
    """
    others = (
        CaseParticipant.objects.active()
        .filter(case_id=participant.case_id, institution_id=old_institution_id)
        .exclude(pk=participant.pk)
    )
    for other in others:
        wanted = {
            "institution_id": participant.institution_id,
            "entity_name_at_filing": participant.entity_name_at_filing,
        }
        if other.person_id is None:
            wanted["name_at_filing"] = participant.entity_name_at_filing
        changed = {
            field: value for field, value in wanted.items() if getattr(other, field) != value
        }
        if not changed:
            continue
        for field, value in changed.items():
            setattr(other, field, value)
        other.updated_by = user
        validated_save(other)


def _first_address(participant):
    """Return the participant's own primary address, or ``None``."""
    own, _ = contacts_of(participant)
    row = next((row for row in own if row.address_id), None)
    return row.address if row else None


def _contact_problems(participant, own_lists, institution_lists, data, institution_field):
    """Return the problems with the contact lists a PATCH sends, as ``{field: …}``.

    Only a person has contacts of their own; an institution's go under
    ``institution_field`` (``institution`` or ``institution_contacts``). Whoever is served must keep an address: an individual
    their own, an institution its own. Accused and witness addresses need a
    police station. Contact details can be declared unknown only while no
    mobile number or email is left.
    """
    problems = {}
    role = participant.role
    if own_lists and not participant.person_id:
        for field in own_lists:
            problems[field] = [
                errors.coded(errors.FIELD_NOT_APPLICABLE, INSTITUTION_CONTACTS_MESSAGE)
            ]
        return problems
    if own_lists.get("addresses") == [] and not participant.institution_id:
        problems["addresses"] = [errors.coded(api_errors.REQUIRED, ADDRESS_REQUIRED_MESSAGE)]
    elif problem := police_station_problems(role, own_lists.get("addresses")):
        problems["addresses"] = problem
    if institution_lists.get("addresses") == []:
        problems[institution_field] = {
            "addresses": [errors.coded(api_errors.REQUIRED, ADDRESS_REQUIRED_MESSAGE)]
        }
    elif problem := police_station_problems(role, institution_lists.get("addresses")):
        problems[institution_field] = {"addresses": problem}
    declared = data.get(
        "contact_details_unknown_declared", participant.contact_details_unknown_declared
    )
    if declared and _has_mobile_or_email(participant, own_lists, institution_lists):
        problems["contact_details_unknown_declared"] = [
            errors.coded(api_errors.INVALID, models.CONTACT_UNKNOWN_MESSAGE)
        ]
    return problems


def _has_mobile_or_email(participant, own_lists, institution_lists):
    """Return whether a mobile number or email is left once the lists sent apply."""
    own, of_institution = contacts_of(participant)
    for lists, rows in ((own_lists, own), (institution_lists, of_institution)):
        for field, contact_type in CONTACT_LISTS.items():
            if contact_type == models.ContactType.ADDRESS:
                continue
            if field in lists:
                if lists[field]:
                    return True
            elif any(row.contact_type == contact_type for row in rows):
                return True
    return False


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
