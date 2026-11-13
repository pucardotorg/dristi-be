"""Mobile numbers, emails and addresses of a case's parties (spec 0020 §4.6).

Each is a ``CaseContact`` row of the case. A participant's own rows carry the
participant (and, for the person acting for an institution, the institution
too); an institution's own rows carry the institution and no participant, so
a shared institution keeps separate contacts in every case.

A list sent in a party write replaces the owner's active rows of that type:
the old rows are deactivated, one save each, so they stay in history.
"""

from collections import defaultdict

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.fields import get_error_detail

from apps.address.models import Address

from .. import errors
from ..models import CaseContact, ContactType
from .services import deactivate, validated_save

# A contact list's request field, and the type of row it holds.
CONTACT_LISTS = {
    "mobile_numbers": ContactType.MOBILE_NUMBER,
    "email_addresses": ContactType.EMAIL,
    "addresses": ContactType.ADDRESS,
}


def load_contacts(participants):
    """Attach each participant's active contacts, and its institution's in its case.

    Sets ``own_contacts`` and ``institution_contacts`` on every participant,
    with one query for all of them. Returns ``participants`` as a list.
    """
    participants = list(participants)
    if not participants:
        return participants
    own = defaultdict(list)
    of_institution = defaultdict(list)
    rows = (
        CaseContact.objects.active()
        .filter(case_id__in={participant.case_id for participant in participants})
        .select_related("address")
        .order_by("contact_type", "ordinal")
    )
    for row in rows:
        if row.case_participant_id:
            own[row.case_participant_id].append(row)
        else:
            of_institution[row.case_id, row.institution_id].append(row)
    for participant in participants:
        participant.own_contacts = own[participant.pk]
        participant.institution_contacts = (
            of_institution[participant.case_id, participant.institution_id]
            if participant.institution_id
            else []
        )
    return participants


def contacts_of(participant):
    """Return ``(own, institution's)`` active contacts, loading them if not yet attached."""
    if not hasattr(participant, "own_contacts"):
        load_contacts([participant])
    return participant.own_contacts, participant.institution_contacts


def first(contacts, contact_type):
    """Return the primary (first) contact of ``contact_type`` in ``contacts``, or ``None``."""
    return next((row for row in contacts if row.contact_type == contact_type), None)


def owner_rows(case, *, participant=None, institution=None):
    """Return the active contacts of one owner: a participant, else an institution in ``case``."""
    rows = CaseContact.objects.active().filter(case=case)
    if participant is not None:
        return rows.filter(case_participant=participant)
    return rows.filter(case_participant__isnull=True, institution=institution)


def save_addresses(addresses, user, path):
    """Store each address sent, reusing identical rows; return them in order.

    ``path`` is where the list was sent, e.g. ``("institution", "addresses")``.
    Two entries that store as the same address are refused at the second.
    """
    saved = []
    problems = {}
    for index, fields in enumerate(addresses):
        try:
            address, _ = Address.objects.get_or_create_address(created_by=user, **fields)
        except DjangoValidationError as exc:
            problems[index] = get_error_detail(exc)
            continue
        if any(address.pk == other.pk for other in saved):
            problems[index] = [errors.coded(errors.DUPLICATE_CONTACT)]
        saved.append(address)
    if problems:
        raise serializers.ValidationError(_nested(path, problems))
    return saved


def replace_contacts(case, user, lists, *, participant=None, institution=None, path=()):
    """Make the lists in ``lists`` the owner's contacts, in order; lists left out are kept.

    The owner is ``participant`` (with ``institution`` too for the person
    acting for one), or ``institution`` alone for an institution's own. A list
    equal to the current one changes nothing.
    """
    for field, contact_type in CONTACT_LISTS.items():
        if field not in lists:
            continue
        if contact_type == ContactType.ADDRESS:
            wanted = save_addresses(lists[field], user, (*path, field))
            key = "address_id"
        else:
            wanted = lists[field]
            key = "value"
        current = list(
            owner_rows(case, participant=participant, institution=institution)
            .filter(contact_type=contact_type)
            .order_by("ordinal")
        )
        wanted_keys = [item.pk if key == "address_id" else item for item in wanted]
        if [getattr(row, key) for row in current] == wanted_keys:
            continue
        for row in current:
            deactivate(row, user)
        for ordinal, item in enumerate(wanted, start=1):
            row = CaseContact(
                case=case,
                case_participant=participant,
                institution=institution,
                contact_type=contact_type,
                ordinal=ordinal,
                created_by=user,
                updated_by=user,
                **({"address": item} if key == "address_id" else {"value": item}),
            )
            validated_save(row)


def move_institution_contacts(case, user, old_institution_id, institution):
    """Re-point the case's contacts of ``old_institution_id`` to ``institution``.

    For a re-linked institution: its own contacts in this case, and those of
    the person acting for it, follow the participant to the new institution.
    """
    for row in CaseContact.objects.active().filter(case=case, institution_id=old_institution_id):
        row.institution = institution
        row.updated_by = user
        row.save(update_fields=["institution", "updated_by", "updated_at"])


def _nested(path, detail):
    """Return ``detail`` nested under each key of ``path`` in turn."""
    for key in reversed(path):
        detail = {key: detail}
    return detail
