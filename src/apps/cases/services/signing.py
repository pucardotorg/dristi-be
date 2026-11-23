"""Who may e-sign a case filing (spec 0015 #6.1, efiling.md §18).

Registered with ``apps.esign`` as the ``CASE_FILING`` authorizer, so it runs
before any request goes to the ESP. A signer may start a transaction only on
the complaint PDF their case is waiting for, one signer at a time, so each
signature lands on the copy the previous signer produced.
"""

import uuid

from apps.esign.constants import ACTIVE_STATUSES, EntityType
from apps.esign.models import ESignTransaction

from ..models import SIGNING_ROLES, CaseParticipant, CaseStatus, ComplaintSigningPackage
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
    is_unsigned_signer = (
        CaseParticipant.objects.active()
        .filter(
            case_id=package.case_id,
            role__in=SIGNING_ROLES,
            has_signed=False,
            person__user=user,
        )
        .exists()
    )
    if not is_unsigned_signer:
        return False
    return not ESignTransaction.objects.filter(
        status__in=ACTIVE_STATUSES,
        entity_type=EntityType.CASE_FILING.value,
        entity_id=str(package.case_id),
    ).exists()


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
