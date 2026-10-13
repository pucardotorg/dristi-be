"""Forgotten-password reset.

A verified password_reset code marks the session, without logging anyone in;
within `PASSWORD_RESET_WINDOW_SECONDS` that session may set the password once.
"""

import time

from django.conf import settings
from django.contrib.auth import get_user_model

from ..models import RegistrationStatus
from .otp import Purpose, verify_and_consume_otp

SESSION_KEY = "password_reset"


def verify_password_reset_code(session, mobile_number, otp) -> bool:
    """Consume a reset code and mark the session as allowed to reset.

    A wrong code, an unknown number and an unfinished registration all return
    False alike, so the result never reveals which numbers hold an account.
    """
    if not verify_and_consume_otp(mobile_number, otp, Purpose.PASSWORD_RESET):
        return False

    user = (
        get_user_model()
        .objects.filter(
            mobile_number=mobile_number,
            is_active=True,
            registration_status=RegistrationStatus.COMPLETE,
        )
        .first()
    )
    if user is None:
        return False

    # The session gains a privilege, so it gets a key no one could have planted.
    session.cycle_key()
    session[SESSION_KEY] = {"user_id": str(user.pk), "verified_at": time.time()}
    return True


def get_password_reset_user(session):
    """Return the account this session may reset, or None if unverified or expired."""
    marker = session.get(SESSION_KEY)
    if not marker:
        return None

    if time.time() - marker["verified_at"] > settings.PASSWORD_RESET_WINDOW_SECONDS:
        del session[SESSION_KEY]
        return None

    return get_user_model().objects.filter(pk=marker["user_id"], is_active=True).first()


def reset_password(session, user, new_password) -> None:
    """Set the password and spend the session's permission to reset.

    The new hash invalidates every session the account already had.
    """
    user.set_password(new_password)
    user.updated_by = user
    user.save(update_fields=["password", "updated_by", "updated_at"])
    del session[SESSION_KEY]
