"""Resolving the person and institution behind a party write (spec 0020 §2.5, §3.4).

Matching is deliberately narrow. The only person ever reused is the caller's
own; everyone else they name is a new row at ``ASSERTED``. An institution is
reused when its PAN or CIN matches, and is then neither changed nor shown, so
naming a company's PAN reveals nothing about what others recorded for it.

Errors are Django ``ValidationError``s; callers turn them into API errors.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import Institution, Person, VerificationLevel, normalize_identifier, pan_cin_errors


def get_or_create_self_person(user):
    """Return ``user``'s own person, creating it from their account the first time.

    A new row is ``VERIFIED``: the account's mobile number was proven at
    registration. An existing row is returned unchanged.
    """
    person, _ = Person.objects.get_or_create(
        user=user,
        defaults={
            "name": user.name,
            "phone_number": user.mobile_number,
            "email_address": user.email,
            "verification_level": VerificationLevel.VERIFIED,
            "created_by": user,
            "updated_by": user,
        },
    )
    return person


def create_asserted_person(user, fields, *, institution=None, designation=None):
    """Create a person ``user`` has named, at ``ASSERTED``, with no attempt to match.

    Their addresses are not the person's: each case keeps them as its contacts.
    """
    return Person.objects.create(
        **fields,
        institution=institution,
        designation=designation if institution else None,
        verification_level=VerificationLevel.ASSERTED,
        created_by=user,
        updated_by=user,
    )


def get_or_create_institution(user, fields):
    """Return the institution with the PAN or CIN in ``fields``, or create one.

    A match is returned as is: none of ``fields`` is applied to it; a type or
    name it lacks is filled separately (``fill_missing_details``). A PAN and a CIN
    belonging to two different institutions are refused, since either could
    be the one meant. A complainant's institution needs a PAN, a CIN or the
    skip declaration (spec 0020 §3.4), but only to be filed: the case filing
    completeness check asks for it, not this write.
    """
    # Normalized as the model stores them, so they match. Their format is
    # checked once, by the model, if a new institution is created.
    pan = normalize_identifier(fields.get("pan"))
    cin = normalize_identifier(fields.get("cin"))
    # Checked before matching too: a match is returned without saving it.
    skip_declared = fields.get("pan_cin_skip_declared", False)
    if problems := pan_cin_errors(pan, cin, skip_declared):
        raise ValidationError(problems)

    found = _find_institution(pan, cin)
    if found is not None:
        return found
    try:
        # A savepoint, so a concurrent insert of the same PAN or CIN can be
        # recovered from without aborting the caller's transaction.
        with transaction.atomic():
            return Institution.objects.create(**fields, created_by=user, updated_by=user)
    except IntegrityError:
        found = _find_institution(pan, cin)
        if found is None:
            raise
        return found


# What a filer may leave out of a new institution and a later filer may fill.
FILLABLE_FIELDS = ("entity_type", "entity_name")


def fill_missing_details(institution, user, fields):
    """Give ``institution`` the type and name in ``fields`` it has none of yet; return whether it did.

    Either may be left out while a filing is drafted, and the institution is
    matched again by its PAN or CIN when the filer sends it later, so this is
    how they are completed. A stored value is never replaced: other filings
    share the row, and the caller refreshes what they show when this returns
    ``True``. The row is locked, so a concurrent filer's values are kept;
    either way ``institution`` ends up with the stored values.
    """
    sent = {
        field: value
        for field in FILLABLE_FIELDS
        if (value := (fields.get(field) or "").strip()) and not getattr(institution, field)
    }
    if not sent:
        return False
    locked = Institution.objects.select_for_update().get(pk=institution.pk)
    filled = [field for field in sent if getattr(locked, field) is None]
    if filled:
        for field in filled:
            setattr(locked, field, sent[field])
        locked.updated_by = user
        locked.save(update_fields=[*filled, "updated_by", "updated_at"])
    for field in (*FILLABLE_FIELDS, "updated_by", "updated_at"):
        setattr(institution, field, getattr(locked, field))
    return bool(filled)


def _find_institution(pan, cin):
    lookup = Q(pk__in=[])
    if pan:
        lookup |= Q(pan=pan)
    if cin:
        lookup |= Q(cin=cin)
    matches = list(Institution.objects.filter(lookup)[:2])
    if len(matches) > 1:
        raise ValidationError(
            {"cin": "This PAN and this CIN belong to two different institutions."}
        )
    return matches[0] if matches else None
