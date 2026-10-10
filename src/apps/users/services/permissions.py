"""Access gates.

Applied as DRF default permission classes so that forgetting to think about
access on a new endpoint fails closed. Endpoints that must be reachable earlier
opt out explicitly.
"""

from rest_framework.permissions import BasePermission

from apps.users import errors


class IsAuthenticatedAndRegistered(BasePermission):
    """Allows only signed-in accounts that finished the registration wizard.

    Checks both halves, because a session issued part-way through registration
    is valid but gated: `POST /users/` sets a cookie before the wizard is done.
    """

    message = errors.REGISTRATION_INCOMPLETE.msg
    code = errors.REGISTRATION_INCOMPLETE.code

    def has_permission(self, request, view):
        """Return whether the caller is signed in and past the wizard."""
        user = request.user
        return bool(user and user.is_authenticated and user.is_registration_complete)


class HasAcceptedCurrentTerms(BasePermission):
    """Allows only accounts holding the terms version currently in force.

    Kept separate from IsAuthenticatedAndRegistered: the remedies differ — one
    sends the user to the wizard, the other to a re-acceptance screen.
    """

    message = errors.TERMS_NOT_CURRENT.msg
    code = errors.TERMS_NOT_CURRENT.code

    def has_permission(self, request, view):
        """Return whether the caller's accepted terms are current."""
        user = request.user
        return bool(user and user.is_authenticated and user.has_current_terms)
