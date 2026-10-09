"""Background tasks for the users app."""

import logging
from functools import partial

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from dramatiq import actor

from apps.dristi_requests.models import Request, RequestType
from apps.dristi_requests.services import create_request

from .verification import VERIFICATIONS

logger = logging.getLogger(__name__)


def schedule_registration_verification(user, file_id=None):
    """Queue the verification request for a just-registered user.

    A no-op for roles that are not verified (litigants). Published only once
    the registration has committed: inside a transaction an immediate send
    would let the worker look for a profile that is not visible yet. Outside
    a transaction ``on_commit`` runs the callback immediately.
    """
    if user.role not in VERIFICATIONS:
        return
    transaction.on_commit(
        partial(_publish_verification, str(user.pk), str(file_id) if file_id else None)
    )


def _publish_verification(user_id, file_id):
    """Hand a committed registration to the worker."""
    request_registration_verification.send(user_id, file_id)


@actor(max_retries=5)
def request_registration_verification(user_id: str, file_id: str | None) -> None:
    """Raise the 0010 request that verifies a registration.

    ``file_id`` is the bar ID document registration already stored; it is
    linked to the request, not uploaded again.

    Idempotent: a retry, or a duplicate message, finds the request already
    raised and does nothing. The user row is locked so two deliveries of the
    same message cannot both pass that check.

    Conditions a retry cannot change (the user or profile is gone) are logged
    and dropped. A missing request type or approver is left to raise, so
    Dramatiq retries it.
    """
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            logger.warning("Verification not requested: no user %s", user_id)
            return

        verification = VERIFICATIONS.get(user.role)
        if verification is None:
            return

        try:
            profile = verification.profile_of(user)
        except ObjectDoesNotExist:
            logger.warning(
                "Verification not requested for user %s: no %s",
                user_id,
                verification.profile_attr,
            )
            return

        request_type = RequestType.objects.active().get(code=verification.request_type_code)

        already_requested = (
            Request.objects.filter(request_type=request_type, requester=user)
            .exclude(status=Request.Status.CANCELLED)
            .exists()
        )
        if already_requested:
            return

        create_request(
            request_type=request_type,
            requester=user,
            data=verification.request_data(profile),
            file_ids=[file_id] if file_id else [],
        )
