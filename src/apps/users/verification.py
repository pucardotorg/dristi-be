"""Verification of an advocate's or clerk's registration through 0010 requests.

Registration stores the claim (the profile, PENDING) and the bar ID document.
Verifying it is a request in ``apps.dristi_requests``, raised in the
background once registration has committed (see ``tasks``); approving that
request is what moves the profile to ACCEPTED, and rejecting it what moves it
to REJECTED (see ``hooks``). A rejected registrant corrects the claim and
resubmits the same request (see ``services.registration``), which moves the
profile back to PENDING.

This module is the one place that says which request type verifies which
role, and what the request carries.
"""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist

from apps.dristi_requests.models import Request, RequestApproval

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

    @property
    def profile_model(self):
        """Return the model of this role's profile."""
        return get_user_model()._meta.get_field(self.profile_attr).related_model

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


def approval_status_of(user):
    """Return where the user's registration stands with the approver.

    ``None`` for roles that are not verified, and for an incomplete
    registration whose profile does not exist yet.
    """
    verification = VERIFICATIONS.get(user.role)
    if verification is None:
        return None
    try:
        profile = verification.profile_of(user)
    except ObjectDoesNotExist:
        return None
    return profile.approval_status


def verification_request_of(user):
    """Return the request verifying the user's registration, if one was raised.

    Cancelled requests are not the registration's any more; of the rest, the
    newest is the one in play.
    """
    verification = VERIFICATIONS.get(user.role)
    if verification is None:
        return None
    return (
        Request.objects.filter(requester=user, request_type__code=verification.request_type_code)
        .exclude(status=Request.Status.CANCELLED)
        .select_related("request_type")
        .order_by("-created_at")
        .first()
    )


def rejection_of(request):
    """Return the approval that rejected the request's current round, if any.

    Its ``comments`` are the approver's reason and ``decided_at`` is when the
    rejection went out. Earlier rounds' rejections are history, not the
    reason the requester is acting on now.
    """
    return (
        request.approvals.filter(version=request.version, status=RequestApproval.Status.REJECTED)
        .order_by("-decided_at")
        .first()
    )
