"""Builders shared by the applications tests (spec 0033 #17).

The fixture world of #17: a registered §138 case in a courtroom; complainant
represented by advocate A1, with clerk C1 working in A1's office; accused
represented by advocate B1; a litigant L1 (an individual complainant whose
advocate files for them) and PoA holder H1 on the complainant side; courtroom
staff S-ord (the three order roles), S-read (no role), S-other (another
court); a scheduled hearing nine days ahead.
"""

import datetime
import itertools
import uuid
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.applications.models import Application, ApplicationType, OfficeMembership
from apps.applications.services import actions, common
from apps.applications.services.common import Action
from apps.cases.models import (
    Case,
    CaseContact,
    CaseParticipant,
    CaseStatus,
    ContactType,
    ParticipantRole,
    Representation,
)
from apps.cases.services.case_types import CaseType
from apps.core.models import Configuration
from apps.esign.constants import ESignStatus
from apps.esign.models import ESignTransaction
from apps.files.tests.factories import make_file
from apps.hearings.services import listing
from apps.organizations.models import Organization, OrganizationType
from apps.parties.models import Person
from apps.parties.tests.factories import make_address
from apps.users.models import AdvocateProfile, ApprovalStatus, RegistrationStatus, Role

User = get_user_model()
_numbers = itertools.count(1)

SEED = settings.BASE_DIR.parent / "data" / "seed" / "core"
# A Thursday: every rule on dates is deterministic (the ``business_date`` fixture).
TODAY = datetime.date(2026, 11, 12)
ORDER_ROLES = ("Order drafter", "Order data filler", "Order signer")
PDF_BYTES = b"%PDF-1.4\n%test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 64


def seed_applications():
    """The types, the default template and the message templates, as every environment seeds them."""
    paths = [
        SEED / "applications",
        SEED / "pdf" / "application_default_template.toml",
        SEED / "pdf" / "application_default_template_v1.toml",
        SEED / "messaging" / "application_templates.toml",
    ]
    call_command("seed", *map(str, paths), "--strict", stdout=StringIO())


def make_user(*groups, name="User", role=None):
    user = User.objects.create_user(
        mobile_number=f"+9197{next(_numbers):08d}",
        name=name,
        role=role,
        registration_status=RegistrationStatus.COMPLETE,
        terms_version_accepted=settings.CURRENT_TERMS_VERSION,
    )
    for group in groups:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


def make_advocate(name="Advocate"):
    user = make_user(name=name, role=Role.ADVOCATE)
    AdvocateProfile.objects.create(
        user=user,
        name=name,
        bar_registration_id=f"KL/{next(_numbers)}/2020",
        approval_status=ApprovalStatus.ACCEPTED,
    )
    return user


def make_court(name, parent=None):
    return Organization.objects.create(
        code=f"{name.upper().replace(' ', '_')}_{next(_numbers)}",
        name=name,
        organization_type=OrganizationType.MAGISTRATE_COURT,
        parent=parent,
    )


def add_party(case, role, name, *, user=None, in_person=False, ordinal=1, phone=None):
    party = CaseParticipant.objects.create(
        case=case,
        person=Person.objects.create(
            name=name, user=user, phone_number=phone or f"+9198{next(_numbers):08d}"
        ),
        role=role,
        ordinal=ordinal,
        name_at_filing=name,
        is_party_in_person=in_person,
        resides_within_jurisdiction=True if role == ParticipantRole.ACCUSED else None,
    )
    CaseContact.objects.create(
        case=case,
        case_participant=party,
        contact_type=ContactType.ADDRESS,
        address=make_address(),
        ordinal=1,
    )
    if phone:
        CaseContact.objects.create(
            case=case,
            case_participant=party,
            contact_type=ContactType.MOBILE_NUMBER,
            value=phone,
            ordinal=1,
        )
    return party


def represent(case, advocate_user, party):
    return Representation.objects.create(
        case=case, advocate=advocate_user.advocate_profile, case_participant=party
    )


def make_case(court, *, status=CaseStatus.REGISTERED, filer=None):
    number = next(_numbers)
    return Case.objects.create(
        case_type=CaseType.CHEQUE_BOUNCE,
        created_by=filer or make_user(name="Filer"),
        court=court,
        status=status,
        case_number=f"ST/{number}/2026" if status == CaseStatus.REGISTERED else None,
        filing_number=f"KL-{number:06d}-2026",
        filed_at=timezone.now(),
        registered_at=timezone.now() if status == CaseStatus.REGISTERED else None,
    )


def set_config(config_set, key, value):
    Configuration.objects.update_or_create(
        config_set=config_set,
        config_key=key,
        defaults={"config_value": value, "is_active": True},
    )


def office(member, advocate_user):
    return OfficeMembership.objects.create(member=member, advocate=advocate_user.advocate_profile)


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def errors_of(response):
    return [(e["code"], e.get("field")) for e in response.json()["errors"]]


def codes_of(response):
    return [e["code"] for e in response.json()["errors"]]


def pdf_upload(name="doc.pdf", content=PDF_BYTES):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def png_upload(name="photo.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def jpeg_upload(name="photo.jpg"):
    return SimpleUploadedFile(name, JPEG_BYTES, content_type="image/jpeg")


def schedule_hearing(case, date, purpose="APPEARANCE"):
    held = listing.hold(
        case_id=case.pk, hearing_date=date, purpose_code=purpose, order_id=uuid.uuid4()
    )
    return listing.confirm(order_id=held.hearing.source_order_id)


def type_row(code):
    return ApplicationType.objects.get(code=code)


def success_esign(application, user):
    """A completed e-sign of the application's copy to sign, as the callback leaves it."""
    signed = make_file(user=user, content_type="application/pdf", file_name="signed.pdf")
    return ESignTransaction.objects.create(
        module="applications",
        entity_type="APPLICATION",
        entity_id=str(application.pk),
        signer=user,
        provider="mock",
        source_file_id=application.signing_file_id,
        signed_file_id=str(signed.pk),
        status=ESignStatus.SUCCESS.value,
        completed_at=timezone.now(),
        expires_at=timezone.now() + datetime.timedelta(minutes=15),
    )


def order_values(**values):
    """*Application action* answers with the spec's defaults for what is not given (#8.2)."""
    base = {"onboard": True, "decides": False, "respond": False}
    base.update(values)
    return {k: (v.isoformat() if isinstance(v, datetime.date) else v) for k, v in base.items()}


def pass_order(application, *, order_id=None, order_date=None, moves_hearing=False, **values):
    """Trigger a stub order carrying an *Application action* item (#17 note)."""
    return actions.apply(
        application.pk,
        order_values(**values),
        order_id=order_id or uuid.uuid4(),
        order_date=order_date,
        moves_hearing=moves_hearing,
    )


def submitted(world, code="GENERIC", *, side="COMPLAINANT", data=None, **fields):
    """An application submitted straight to ``PENDING_REVIEW`` (or ``SUBMITTED``), as filing leaves it."""
    from apps.applications.services import numbering
    from apps.applications.services.calendar import next_working_day

    advocate = world.a1 if side == "COMPLAINANT" else world.b1
    litigant = world.complainant if side == "COMPLAINANT" else world.accused
    application = Application.objects.create(
        case=world.case,
        application_type=type_row(code),
        status="DRAFT",
        side=side,
        created_by=advocate,
        raised_by=advocate,
        raised_on_behalf_of=litigant.pk,
        details="<p>Because.</p>",
        data=data or ({"title": "Request"} if code == "GENERIC" else {}),
        hearing_id=fields.pop("hearing_id", None),
        objection_to=fields.pop("objection_to", None),
        signed_file_id="signed-file",
        **fields,
    )
    with __import__("django.db", fromlist=["transaction"]).transaction.atomic():
        application = common.lock(application.pk)
        application.submitted_at = timezone.now()
        numbering.allot_submission_number(application)
        if application.is_objection:
            common.transition(
                application, Action.SUBMIT, advocate, to_status="SUBMITTED", check=False
            )
        else:
            application.review_due_date = next_working_day(application.case.court_id, TODAY)
            common.transition(
                application, Action.SUBMIT, advocate, to_status="PENDING_REVIEW", check=False
            )
    return Application.objects.get(pk=application.pk)


def pay_demand(demand_id, user, *, deliver=True):
    """Pay the whole demand and, as the completion actor would, announce it."""
    from apps.payments.models import Demand
    from apps.payments.providers.registry import reset_cache
    from apps.payments.services.payments import PaymentService
    from apps.payments.tasks import notify_payment_completed

    reset_cache()
    demand = Demand.objects.get(pk=demand_id)
    payment = PaymentService.create_payment(
        demand=demand,
        demand_item_ids=list(demand.items.values_list("pk", flat=True)),
        client_request_id=f"pay-{uuid.uuid4()}",
        actor=user,
    ).payment
    PaymentService.confirm_payment(payment, actor=user)
    if deliver:
        notify_payment_completed.fn(str(payment.pk))
    return payment


def file_bytes(file_id):
    from apps.files.services import get_file_content

    with get_file_content(file_id) as handle:
        return handle.read()
