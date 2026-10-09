"""Completing the registration wizard.

The state change that ends registration lives here rather than in the view, so
the rule "the profile row and the account never disagree" is stated once and is
testable without an HTTP request.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.files.documents import discard_documents, store_documents

from ..models import RegistrationStatus


class DocumentRejected(Exception):  # noqa: N818
    """Raised when the files module refuses a registration document."""

    def __init__(self, messages):
        super().__init__(messages)
        self.messages = messages


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


def complete_registration_with_document(*, user, document, document_tag, **registration):
    """Store a registration document, then complete registration.

    The document is stored through ``apps.files`` against the registrant, with
    ``document_tag`` recording which document it is.

    The upload runs first and outside the registration transaction:
    ``upload_file`` writes to Object Storage before its row, so a rollback
    around it would leave the object behind with no row to find it by. If
    registration then fails, the stored file is deleted and the original error
    is raised.

    Returns ``(profile, file_id)``.
    """
    try:
        [file_id] = store_documents([document], user_id=user.pk, tags=[document_tag])
    except ValidationError as exc:
        raise DocumentRejected(exc.messages) from exc

    try:
        profile = complete_registration(user=user, **registration)
    except Exception:
        discard_documents([file_id])
        raise
    return profile, file_id
