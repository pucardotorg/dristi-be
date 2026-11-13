"""Builders shared by the hearings tests.

Hearings get their dates the way the product gives them: through the orders
contract (``listing.hold`` then ``listing.confirm``), never by writing rows.
"""

import datetime
import itertools
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.cases.models import Case, CaseParticipant, CaseStatus, ParticipantRole, Representation
from apps.cases.services.case_types import CaseType
from apps.core.models import Configuration
from apps.hearings.services import listing
from apps.organizations.models import Organization, OrganizationType
from apps.parties.models import Person
from apps.parties.tests.factories import make_address
from apps.users.models import AdvocateProfile, ApprovalStatus, RegistrationStatus

User = get_user_model()
_numbers = itertools.count(1)

# The business date every test runs on: a Thursday (``business_date`` fixture).
TODAY = datetime.date(2026, 11, 12)
MON, TUE, WED, THU, FRI, SAT, SUN = (datetime.date(2026, 11, day) for day in range(16, 23))


def make_user(*roles, name="User"):
    """Return a registered account holding the hearing ``roles`` (placeholder groups)."""
    user = User.objects.create_user(
        mobile_number=f"+91920000{next(_numbers):04d}",
        name=name,
        registration_status=RegistrationStatus.COMPLETE,
        terms_version_accepted=settings.CURRENT_TERMS_VERSION,
    )
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def make_court(name, parent=None):
    return Organization.objects.create(
        code=f"{name.upper().replace(' ', '_')}_{next(_numbers)}",
        name=name,
        organization_type=OrganizationType.MAGISTRATE_COURT,
        parent=parent,
    )


def _party(case, role, name, user=None, in_person=True):
    return CaseParticipant.objects.create(
        case=case,
        person=Person.objects.create(
            name=name, user=user, phone_number=f"+9198{next(_numbers):08d}"
        ),
        role=role,
        ordinal=1,
        name_at_filing=name,
        address=make_address(),
        is_party_in_person=in_person,
    )


def make_case(
    court,
    *,
    complainant_user=None,
    accused_user=None,
    advocate_user=None,
    filed_days_ago=10,
    status=CaseStatus.REGISTERED,
):
    """Return a registered case in ``court`` with a complainant and an accused.

    With ``advocate_user``, an approved advocate represents the complainant.
    """
    number = next(_numbers)
    case = Case.objects.create(
        case_type=CaseType.CHEQUE_BOUNCE,
        created_by=make_user(name="Filer"),
        court=court,
        status=status,
        case_number=f"CC/{number}/2026" if status == CaseStatus.REGISTERED else None,
        filing_number=f"F/{number}/2026",
        filed_at=timezone.now() - datetime.timedelta(days=filed_days_ago),
        registered_at=timezone.now() if status == CaseStatus.REGISTERED else None,
    )
    complainant = _party(
        case,
        ParticipantRole.COMPLAINANT,
        f"Complainant {number}",
        complainant_user,
        in_person=advocate_user is None,
    )
    _party(case, ParticipantRole.ACCUSED, f"Accused {number}", accused_user)
    if advocate_user is not None:
        advocate = AdvocateProfile.objects.create(
            user=advocate_user,
            name=advocate_user.name,
            bar_registration_id=f"KA/{number}/2020",
            approval_status=ApprovalStatus.ACCEPTED,
        )
        Representation.objects.create(case=case, advocate=advocate, case_participant=complainant)
    return case


def set_config(key, value):
    Configuration.objects.update_or_create(
        config_set="hearings", config_key=key, defaults={"config_value": value, "is_active": True}
    )


def hold(case, date, purpose="APPEARANCE", order_id=None, **kwargs):
    """Hold a date for ``case`` in a draft order; return the ``HoldResult``."""
    return listing.hold(
        case_id=case.pk,
        hearing_date=date,
        purpose_code=purpose,
        order_id=order_id or uuid.uuid4(),
        **kwargs,
    )


def schedule(case, date, purpose="APPEARANCE", **kwargs):
    """Hold and confirm a date for ``case``, as a triggered order does; return the hearing."""
    held = hold(case, date, purpose, **kwargs)
    return listing.confirm(order_id=held.hearing.source_order_id)


def code(excinfo):
    """The registered code of a raised ``BusinessError`` or ``HearingError``."""
    error = excinfo.value
    return error.error.code


def field(excinfo):
    detail = getattr(excinfo.value, "detail", None)
    return next(iter(detail)) if isinstance(detail, dict) else None
