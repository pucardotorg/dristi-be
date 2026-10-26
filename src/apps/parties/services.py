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

from .models import Institution, Person, VerificationLevel, normalize_identifier


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


def create_asserted_person(user, fields, *, institution=None, designation=None, address=None):
    """Create a person ``user`` has named, at ``ASSERTED``, with no attempt to match.

    ``address``, when given, becomes their correspondence address.
    """
    return Person.objects.create(
        **fields,
        institution=institution,
        designation=designation if institution else None,
        correspondence_address=address,
        verification_level=VerificationLevel.ASSERTED,
        created_by=user,
        updated_by=user,
    )


def get_or_create_institution(user, fields, *, address=None):
    """Return the institution with the PAN or CIN in ``fields``, or create one.

    A match is returned as is: none of ``fields`` is applied to it. A new
    institution gets ``address`` as its registered office. A PAN and a CIN
    belonging to two different institutions are refused, since either could
    be the one meant.
    """
    # Normalized as the model stores them, so they match. Their format is
    # checked once, by the model, if a new institution is created.
    pan = normalize_identifier(fields.get("pan"))
    cin = normalize_identifier(fields.get("cin"))

    found = _find_institution(pan, cin)
    if found is not None:
        return found
    try:
        # A savepoint, so a concurrent insert of the same PAN or CIN can be
        # recovered from without aborting the caller's transaction.
        with transaction.atomic():
            return Institution.objects.create(
                **fields, address=address, created_by=user, updated_by=user
            )
    except IntegrityError:
        found = _find_institution(pan, cin)
        if found is None:
            raise
        return found


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
