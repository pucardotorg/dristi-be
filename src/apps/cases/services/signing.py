"""Who may e-sign a case filing (spec 0015 #6.1, efiling.md §18).

Registered with ``apps.esign`` as the ``CASE_FILING`` authorizer, so it runs
before any request goes to the ESP. A signer may start a transaction only on
the complaint PDF their case is waiting for, one signer at a time, so each
signature lands on the copy the previous signer produced.

Each party signs for themselves (efiling.md §18): "each party must log in with
the phone number entered for them in order to sign -- creating their account".
So a signer is the participant's own account when their person has one, and
otherwise the account whose mobile number is the participant's mobile number
on the case -- the number the filer entered and the party logs in with
(account-creation.md "Implicit account creation at signing"). Nobody signs for
another person; a filer is never a signer on someone else's behalf.
"""

import uuid

from django.db.models import OuterRef, Q, Subquery

from apps.esign.constants import ACTIVE_STATUSES, EntityType
from apps.esign.models import ESignTransaction

from ..models import (
    SIGNING_ROLES,
    CaseContact,
    CaseParticipant,
    CaseStatus,
    ComplaintSigningPackage,
    ContactType,
)
from ..models import SigningPackageStatus as Status


def can_sign_case_filing(*, user, entity_type, entity_id, organization_id=None, file_id=None):
    """Whether ``user`` may e-sign ``file_id`` as the filing of case ``entity_id``.

    True only while the case is pending signature, ``file_id`` is the open
    signing package's current file, ``user`` is a signer of the case
    (``SIGNING_ROLES``) who has not signed yet, and no other e-sign of the
    case is in progress.
    """
    package = (
        ComplaintSigningPackage.objects.filter(
            case_id=_uuid_or_none(entity_id),
            case__status=CaseStatus.PENDING_SIGN,
            status=Status.OPEN,
        )
        .only("case_id", "current_file_id")
        .first()
    )
    if package is None or not file_id or str(file_id) != str(package.current_file_id):
        return False
    unsigned = CaseParticipant.objects.active().filter(
        case_id=package.case_id, role__in=SIGNING_ROLES, has_signed=False
    )
    if not unsigned.filter(signer_q(user)).exists():
        return False
    return not ESignTransaction.objects.filter(
        status__in=ACTIVE_STATUSES,
        entity_type=EntityType.CASE_FILING.value,
        entity_id=str(package.case_id),
    ).exists()


def signer_q(user):
    """Match the participants ``user`` signs as: their own person, else by their mobile number.

    A person with an account signs only from that account. A person with none
    signs from the account registered to their primary mobile number on the
    case (the first ``MOBILE_NUMBER`` contact, efiling ``LIT-3``/``LIT-13``),
    which logging in with that number creates (§18).
    """
    own_mobile = (
        CaseContact.objects.active()
        .filter(
            case_participant_id=OuterRef("pk"),
            contact_type=ContactType.MOBILE_NUMBER,
        )
        .order_by("ordinal")
        .values("value")[:1]
    )
    return Q(person__user=user) | Q(
        person__user__isnull=True, pk__in=_participants_with_mobile(user, own_mobile)
    )


def is_signer(participant, user):
    """Whether ``user`` signs as ``participant`` (see ``signer_q``)."""
    return CaseParticipant.objects.filter(pk=participant.pk).filter(signer_q(user)).exists()


def _participants_with_mobile(user, own_mobile):
    mobile = getattr(user, "mobile_number", None)
    if not mobile:
        return CaseParticipant.objects.none().values("pk")
    return (
        CaseParticipant.objects.annotate(primary_mobile=Subquery(own_mobile))
        .filter(primary_mobile=mobile)
        .values("pk")
    )


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
