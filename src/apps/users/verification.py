"""Verification of an advocate's or clerk's registration through 0010 requests.

Registration stores the claim (the profile, PENDING) and the bar ID document.
Verifying it is a request in ``apps.dristi_requests``, raised in the
background once registration has committed (see ``tasks``); approving that
request is what moves the profile to ACCEPTED (see ``hooks``).

This module is the one place that says which request type verifies which
role, and what the request carries.
"""

from dataclasses import dataclass

from .models import Role

ADVOCATE_REGISTRATION = "ADVOCATE_REGISTRATION"
CLERK_REGISTRATION = "CLERK_REGISTRATION"


@dataclass(frozen=True)
class Verification:
    """How one role's registration is verified."""

    request_type_code: str
    # Related name of the profile on the user, e.g. ``advocate_profile``.
    profile_attr: str
    # Profile field holding the registration number the request verifies.
    number_field: str

    def profile_of(self, user):
        """Return the user's profile for this role."""
        return getattr(user, self.profile_attr)

    def request_data(self, profile):
        """Return the request's ``data``, matching the request type's schema."""
        return {
            "name": profile.name,
            self.number_field: getattr(profile, self.number_field),
        }


VERIFICATIONS = {
    Role.ADVOCATE: Verification(ADVOCATE_REGISTRATION, "advocate_profile", "bar_registration_id"),
    Role.CLERK: Verification(CLERK_REGISTRATION, "clerk_profile", "clerk_registration_number"),
}

VERIFICATIONS_BY_CODE = {v.request_type_code: v for v in VERIFICATIONS.values()}
