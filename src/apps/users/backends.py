"""Authentication backends.

`ModelBackend` covers mobile + password unchanged, since it authenticates against
whatever `USERNAME_FIELD` names. This adds mobile + OTP alongside it.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from .otp import Purpose, verify_and_consume_otp


class OTPBackend(BaseBackend):
    """Authenticates a mobile number against a one-time code."""

    def authenticate(self, request, mobile_number=None, otp=None, purpose=Purpose.LOGIN, **kwargs):
        """Return the account the code belongs to, consuming the code.

        Returning None means "not my credential type"; Django then tries the
        next backend in AUTHENTICATION_BACKENDS.
        """
        if not (mobile_number and otp):
            return None

        if not verify_and_consume_otp(mobile_number, otp, purpose):
            return None

        user = get_user_model().objects.filter(mobile_number=mobile_number).first()

        # An inactive account is disabled; an incomplete one is not, and must
        # still be able to log in so registration can be resumed.
        if user is None or not user.is_active:
            return None
        return user

    def get_user(self, user_id):
        """Reload the user a session cookie points at."""
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()
