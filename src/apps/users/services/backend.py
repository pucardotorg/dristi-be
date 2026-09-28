"""Authentication backends.

`ModelBackend` covers mobile + password unchanged, since it authenticates against
whatever `USERNAME_FIELD` names. This adds mobile + OTP alongside it.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .otp import Purpose, verify_and_consume_otp


class OTPBackend(ModelBackend):
    """Authenticates a mobile number against a one-time code.

    Subclasses ModelBackend rather than BaseBackend so `get_user`,
    `user_can_authenticate` and the permission lookups are inherited; only the
    credential check differs.
    """

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

        # user_can_authenticate rejects disabled accounts. An incomplete
        # registration is not disabled, so it still passes and can be resumed.
        if user is None or not self.user_can_authenticate(user):
            return None
        return user
