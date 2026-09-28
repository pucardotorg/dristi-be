"""Model-level behaviour that no endpoint exercises directly."""

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.users.models import RegistrationStatus, User

from .base import MOBILE


class TermsCurrencyTests(APITestCase):
    """Terms currency is a separate question from registration status."""

    @override_settings(CURRENT_TERMS_VERSION=3)
    def test_stale_terms_do_not_make_registration_incomplete(self):
        """An account can be COMPLETE and still owe a re-acceptance."""
        user = User.objects.create_user(
            mobile_number=MOBILE,
            registration_status=RegistrationStatus.COMPLETE,
            terms_version_accepted=1,
        )
        self.assertTrue(user.is_registration_complete)
        self.assertFalse(user.has_current_terms)
