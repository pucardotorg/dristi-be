"""The application on paper (spec 0033 #6.5, #6.5a, #14.4 ``document``).

One structure serves three readers: the filer's preview, the PDF that is signed,
and the court's ``document``. Values come from the case and the application,
never the client. The court heading and offence follow the case's court and
case type.
"""

import datetime

from django.conf import settings

from apps.cases.models import ParticipantRole, Representation
from apps.cases.services.complaint_pdf import LONG_TITLES
from apps.pdf.services.config_loader import PDFConfigLoader
from apps.pdf.services.context import RequestContext
from apps.pdf.services.documents import store_document, tags_for
from apps.pdf.services.generator import render_document_with_anchors

from .. import ports
from ..enums import Side
from . import richtext

DEFAULT_TEMPLATE = "application-default"
SIGNATURE_KEY = "raised_by"
ROLE_LABEL = {ParticipantRole.COMPLAINANT: "Complainant", ParticipantRole.ACCUSED: "Accused"}


def template_key(application):
    return application.application_type.template_code or DEFAULT_TEMPLATE


def dated(day):
    """``12 November 2026``."""
    return f"{day.day} {day:%B %Y}"


def _advocates(case_id):
    """``{participant_id: [advocate name, ...]}`` of the case's active representations."""
    found = {}
    for rep in (
        Representation.objects.filter(case_id=case_id, is_active=True, to_date__isnull=True)
        .select_related("advocate__user")
        .order_by("from_date")
    ):
        found.setdefault(rep.case_participant_id, []).append(
            f"Adv. {rep.advocate.name or rep.advocate.user.name}"
        )
    return found


def _party_name(participant):
    return participant.name_at_filing or participant.entity_name_at_filing or ""


def build(application, *, day=None):
    """The structured render of #6.5a."""
    case = application.case
    court = case.court
    litigants = ports.participants(case.pk)
    advocates = _advocates(case.pk)
    complainants = [p for p in litigants if p.role == ParticipantRole.COMPLAINANT]
    accused = [p for p in litigants if p.role == ParticipantRole.ACCUSED]
    parties = []
    for party in [*complainants, *accused]:
        group = [{"term": ROLE_LABEL[party.role], "value": _party_name(party)}]
        group.extend({"term": "Advocate", "value": name} for name in advocates.get(party.pk, []))
        parties.append(group)
    offence = LONG_TITLES.get(case.case_type, case.get_case_type_display())
    parties.append([{"term": "Offence", "value": offence}])

    litigant = ports.participant(case.pk, application.raised_on_behalf_of)
    spec = application.spec
    day = day or (application.submitted_at.date() if application.submitted_at else _today())
    first = _party_name(complainants[0]) if complainants else ""
    against = _party_name(accused[0]) if accused else ""
    return {
        "application_id": str(application.pk),
        "court": f"Before the {court.name}" if court else "",
        "case_number": case.case_number or case.filing_number or "",
        "matter": f"In the matter of {first} v. {against}" if first and against else "",
        "title": spec.render_title(application),
        "filed_for": _party_name(litigant) if litigant else "",
        "parties": parties,
        "entries": spec.render_entries(application),
        "details": application.details,
        "signatory": _signatory(application, litigant),
        "dated": day.isoformat(),
    }


def _signatory(application, litigant):
    raised_by = application.raised_by
    side = Side(application.side).label.lower()
    if raised_by is None:
        return {"signature": "", "name": "", "line": ""}
    option = next(
        (
            o
            for o in ports.advocate_options(application.case_id, application.side)
            if o.user_id == raised_by.pk
        ),
        None,
    )
    if option is not None and option.kind == "ADVOCATE":
        return {
            "signature": "Advocate Signature",
            "name": option.name,
            "line": f"Advocate for the {side}",
        }
    return {
        "signature": "Signature",
        "name": _party_name(litigant) if litigant else raised_by.name,
        "line": f"{Side(application.side).label} in person",
    }


def pdf_payload(application, structure, *, draft):
    """The template's request data, from the structure (#6.5)."""
    signatory = structure["signatory"]
    return {
        **structure,
        "draft": draft,
        "dated": dated(datetime.date.fromisoformat(structure["dated"])),
        "paragraphs": [
            line for line in richtext.to_text(structure["details"]).split("\n") if line.strip()
        ],
        "signatories": [
            {"key": SIGNATURE_KEY, "name": signatory["name"], "label": signatory["line"]}
        ],
    }


def render(application, user, *, draft=False):
    """Render the application's template; return ``(pdf_bytes, anchors)``. Raises ``PDFError``."""
    key = template_key(application)
    config = PDFConfigLoader.load(key)[2]
    context = RequestContext(
        tenant_id=settings.CASE_PDF_TENANT_ID,
        key=key,
        entity_id=str(application.pk),
        user_id=str(getattr(user, "pk", "") or ""),
    )
    payload = pdf_payload(application, build(application), draft=draft)
    return render_document_with_anchors(config, payload, context)


def render_and_store(application, user):
    """Render the copy to sign, store it; return ``(file_id, placeholder)`` (#6.5 step 4)."""
    content, anchors = render(application, user)
    file_id = store_document(
        content,
        filename=f"application-{application.pk}.pdf",
        user_id=user.pk,
        tags=tags_for(template_key(application), str(application.pk)),
    )
    return file_id, anchors.get(SIGNATURE_KEY, {})


def _today():
    from apps.hearings.services.calendar import business_date

    return business_date()
