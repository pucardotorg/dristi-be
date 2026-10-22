"""Terms acceptance (spec 0005 section 6), shared by the wizard and POST /users/me/terms."""

from django.conf import settings
from django.utils import timezone


def stamp_current_terms(user):
    """Record acceptance of the terms in force on `user`, without saving.

    Both values come from the server: a client-supplied timestamp or version is
    unverifiable and therefore worthless as evidence.
    """
    user.terms_accepted_at = timezone.now()
    user.terms_version_accepted = settings.CURRENT_TERMS_VERSION


def accept_current_terms(user):
    """Record and save acceptance of the terms in force.

    A no-op when the account already holds the current version: re-stamping
    would replace the moment of acceptance with the moment of a repeat click.
    """
    if user.has_current_terms:
        return

    stamp_current_terms(user)
    user.updated_by = user
    user.save(
        update_fields=["terms_accepted_at", "terms_version_accepted", "updated_by", "updated_at"]
    )
