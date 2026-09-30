"""Completing the registration wizard.

The state change that ends registration lives here rather than in the view, so
the rule "the profile row and the account never disagree" is stated once and is
testable without an HTTP request.
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import RegistrationStatus


@transaction.atomic
def complete_registration(
    *,
    user,
    role,
    profile_model,
    name,
    password,
    email=None,
    profile_fields=None,
):
    """Fill in the account, create its profile, and mark registration complete.

    Runs in one transaction: either both the account and the profile land, or
    neither does, so the two can never disagree about whether the wizard
    finished.

    Terms acceptance is stamped from the server clock and server configuration;
    a client-supplied timestamp or version is unverifiable and is never used.

    The account and its profile are attributed to the account itself: the
    registrant is the actor here, so leaving the audit fields NULL would say
    "origin unknown" about the one row whose origin is certain.

    Returns the profile that was created.
    """
    user.name = name
    # "" would collide on the unique index; NULL is the absence of an email.
    user.email = email or None
    user.role = role
    user.set_password(password)
    user.terms_accepted_at = timezone.now()
    user.terms_version_accepted = settings.CURRENT_TERMS_VERSION
    user.registration_status = RegistrationStatus.COMPLETE
    user.updated_by = user
    if user.created_by_id is None:
        user.created_by = user
    user.save()

    # approval_status is deliberately not settable here: a new claim is always
    # PENDING, and only a 0010 request moves it.
    return profile_model.objects.create(
        user=user,
        name=name,
        created_by=user,
        updated_by=user,
        **(profile_fields or {}),
    )
