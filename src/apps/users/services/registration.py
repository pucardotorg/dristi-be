"""Completing the registration wizard.

The state change that ends registration lives here rather than in the view, so
the rule "the profile row and the account never disagree" is stated once and is
testable without an HTTP request.
"""

from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.dristi_requests import services as request_services
from apps.files.documents import discard_documents, store_documents

from ..documents import BAR_COUNCIL_ID_TAG
from ..models import ApprovalStatus, RegistrationStatus
from ..verification import VERIFICATIONS, rejection_of, verification_request_of
from .terms import stamp_current_terms


class DocumentRejected(Exception):  # noqa: N818
    """Raised when the files module refuses a registration document."""

    def __init__(self, messages):
        super().__init__(messages)
        self.messages = messages


class RegistrationNotRejected(Exception):  # noqa: N818
    """Raised when a resubmission finds no rejected registration to correct."""


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
    stamp_current_terms(user)
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


def complete_registration_with_document(*, user, document, **registration):
    """Store the bar ID document, if one was sent, then complete registration.

    See ``_stored_document`` for why the upload runs first and outside the
    registration transaction.

    Returns ``(profile, file_id)``; ``file_id`` is ``None`` without a document.
    """
    with _stored_document(user, document) as file_id:
        return complete_registration(user=user, **registration), file_id


def resubmit_registration(*, user, name, email, registration_number, document=None):
    """Correct a rejected registration and send the same request back for approval.

    The account and profile take the corrected values, the profile returns to
    PENDING, and the verification request is resubmitted with the new claim:
    the same request row, so the application keeps its id; only its version
    moves on. A new ``document`` replaces the one the approver saw; without
    one, the request keeps its documents.

    Returns the resubmitted request.
    """
    with _stored_document(user, document) as file_id:
        return _resubmit_registration(
            user=user,
            name=name,
            email=email,
            registration_number=registration_number,
            file_id=file_id,
        )


def describe_rejected_registration(user):
    """Return what the correction screens show a rejected registrant.

    The approver's reason is read from the request's current round rather
    than copied onto the profile, so there is one place it is recorded.
    Raises ``RegistrationNotRejected`` when there is nothing to correct.
    """
    verification = VERIFICATIONS[user.role]
    profile = verification.profile_of(user)
    request = _request_to_correct(user, profile)

    rejection = rejection_of(request)
    document = request.documents.select_related("file").first()
    return {
        "application_id": request.pk,
        "approval_status": profile.approval_status,
        "role": user.role,
        "officer_message": rejection.comments if rejection else "",
        "rejected_at": rejection.decided_at if rejection else None,
        "name": profile.name,
        "email": user.email,
        "mobile_number": user.mobile_number,
        "registration_number": getattr(profile, verification.number_field),
        "document": (
            {"file_id": document.file_id, "file_name": document.filename} if document else None
        ),
    }


@transaction.atomic
def _resubmit_registration(*, user, name, email, registration_number, file_id):
    """Apply the corrections and resubmit, atomically."""
    verification = VERIFICATIONS[user.role]
    # Locked so two resubmissions cannot both find the profile REJECTED.
    profile = verification.profile_model.objects.select_for_update().get(user=user)
    request = _request_to_correct(user, profile)

    user.name = name
    # "" would collide on the unique index; NULL is the absence of an email.
    user.email = email or None
    user.updated_by = user
    user.save(update_fields=["name", "email", "updated_by", "updated_at"])

    profile.name = name
    setattr(profile, verification.number_field, registration_number)
    profile.approval_status = ApprovalStatus.PENDING
    profile.updated_by = user
    profile.save(
        update_fields=[
            "name",
            verification.number_field,
            "approval_status",
            "updated_by",
            "updated_at",
        ]
    )

    return request_services.resubmit(
        request,
        actor=user,
        data=verification.request_data(profile),
        file_ids=[file_id] if file_id is not None else None,
    )


def _request_to_correct(user, profile):
    """Return the rejected verification request, or raise ``RegistrationNotRejected``."""
    request = verification_request_of(user)
    if profile.approval_status != ApprovalStatus.REJECTED or request is None:
        raise RegistrationNotRejected()
    return request


@contextmanager
def _stored_document(user, document):
    """Store the bar ID against the registrant, and delete it if the block fails.

    Yields the file id, or ``None`` when there is no document. The upload runs
    first and outside any transaction: ``upload_file`` writes to Object
    Storage before its row, so a rollback around it would leave the object
    behind with no row to find it by.
    """
    if document is None:
        yield None
        return

    try:
        [file_id] = store_documents([document], user_id=user.pk, tags=[BAR_COUNCIL_ID_TAG])
    except ValidationError as exc:
        raise DocumentRejected(exc.messages) from exc

    try:
        yield file_id
    except Exception:
        discard_documents([file_id])
        raise
