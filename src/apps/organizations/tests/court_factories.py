"""Fixtures for the court roles tests (spec 0029 #12)."""

from itertools import count

from apps.organizations import services
from apps.organizations.enums import CourtLevel
from apps.organizations.models import CourtRole, OrganizationType
from apps.organizations.tests.factories import make_organization
from apps.users.models import User

_numbers = count(1)


def make_user(**kwargs):
    """Create an active user with a unique mobile number."""
    number = kwargs.pop("mobile_number", None) or f"+91900000{next(_numbers):04d}"
    return User.objects.create_user(mobile_number=number, password="x", **kwargs)


def make_establishment(code, **kwargs):
    """Create a court establishment."""
    return make_organization(
        code=code,
        name=kwargs.pop("name", code),
        organization_type=OrganizationType.MAGISTRATE_COURT,
        court_level=CourtLevel.ESTABLISHMENT,
        **kwargs,
    )


def make_courtroom(code, establishment, **kwargs):
    """Create a courtroom of ``establishment``."""
    return make_organization(
        code=code,
        name=kwargs.pop("name", code),
        organization_type=OrganizationType.MAGISTRATE_COURT,
        court_level=CourtLevel.COURTROOM,
        parent=establishment,
        **kwargs,
    )


def make_role(code, actions=(), *, establishment=None, name=None, actor=None):
    """Create a role holding ``actions`` (constants, or ``(action, scope)`` pairs)."""
    role = services.save_role(
        CourtRole(code=code, name=name or code.title(), establishment=establishment), actor=actor
    )
    services.set_role_actions(role, list(actions), actor=actor)
    return role


def assign(user, organization, role, *, actor=None):
    """Give ``user`` the role; at a courtroom, put it on their list first."""
    if organization.court_level == CourtLevel.COURTROOM:
        services.assign_courtroom(user, organization, actor=actor)
    return services.assign_role(user, organization, role, actor=actor)


class TwoCourtsMixin:
    """Two establishments with two courtrooms each: A (A1, A2) and B (B1, B2)."""

    def make_courts(self):
        self.est_a = make_establishment("EST_A", name="Establishment A")
        self.room_a1 = make_courtroom("EST_A_CR1", self.est_a, name="Courtroom A1")
        self.room_a2 = make_courtroom("EST_A_CR2", self.est_a, name="Courtroom A2")
        self.est_b = make_establishment("EST_B", name="Establishment B")
        self.room_b1 = make_courtroom("EST_B_CR1", self.est_b, name="Courtroom B1")
        self.room_b2 = make_courtroom("EST_B_CR2", self.est_b, name="Courtroom B2")
