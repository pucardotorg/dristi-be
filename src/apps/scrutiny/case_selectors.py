"""Stand-ins for the ``apps.cases`` selectors scrutiny reads (spec 0024 #1.1).

``get_case_summaries``, ``get_filing_view``, ``get_bundle``,
``plugin.checklist`` and ``plugin.check_facts`` are not exposed by
``apps.cases`` yet. These build the same shapes from the case's rows, so the
read models of #7 work now; each is replaced by the cases function of the
same name when it lands. Writes stay in ``ports``.
"""

import datetime
from collections import defaultdict

from django.db.models import Prefetch
from django.utils import timezone

from apps.cases.models import (
    PARTICIPANT_ORDERING,
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    ParticipantRole,
    Representation,
)
from apps.cases.services.case_types import DocumentType, EvidenceType, get_config

from . import ports

# Party lists: complainants, then accused.
PARTY_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.ACCUSED)
# A cheque is valid for three months from its date (RBI; SCR-08a).
CHEQUE_VALIDITY_MONTHS = 3

CHECKLIST = (
    "Names match across cheque, ID and notice",
    "Cheque details match the instrument",
    "Notice within 30 days of return memo",
    "Filing within limitation or condonation prayed",
    "Jurisdiction consistent with addresses",
    "Signatures on complaint and affidavit",
    "All documents legible and the right ones",
)

# What a numbered record of each section is called on the detail screen.
RECORD_TITLES = {"CHQ": "Cheque", "LDN": "Notice"}


def _local_date(moment):
    return timezone.localdate(moment) if moment else None


def _parties(participants, title=None):
    """Return ``"A v. B"``: the court's title where it set one, else the first party of each side."""
    title = title or {}
    names = defaultdict(list)
    for participant in participants:
        names[participant.role].append(participant.name_at_filing)

    def side(role, key):
        listed = names[role]
        if title.get(key):
            return title[key]
        if not listed:
            return ""
        return f"{listed[0]} and others" if len(listed) > 1 else listed[0]

    return f"{side(ParticipantRole.COMPLAINANT, 'complainant')} v. {side(ParticipantRole.ACCUSED, 'accused')}"


def _advocate_name(representation):
    profile = representation.advocate
    return f"Adv. {profile.name or profile.user.name}"


def get_case_summaries(case_ids):
    """Return list-row facts for each case, by id, in a fixed number of queries."""
    cases = Case.objects.filter(pk__in=list(case_ids)).prefetch_related(
        Prefetch(
            "participants",
            queryset=CaseParticipant.objects.active()
            .filter(role__in=PARTY_ROLES)
            .order_by(*PARTICIPANT_ORDERING),
            to_attr="party_rows",
        ),
        Prefetch(
            "representations",
            queryset=Representation.objects.active()
            .filter(case_participant__role=ParticipantRole.COMPLAINANT)
            .select_related("advocate__user")
            .order_by("from_date"),
            to_attr="advocate_rows",
        ),
    )
    titles = _case_titles(cases)
    summaries = {}
    for case in cases:
        advocates = list(dict.fromkeys(_advocate_name(row) for row in case.advocate_rows))
        summaries[case.pk] = {
            "id": case.pk,
            "filing_number": case.filing_number,
            "case_number": case.case_number,
            "parties": _parties(case.party_rows, titles.get(case.pk)),
            "case_type": {"key": case.case_type, "label": case.get_case_type_display()},
            "advocates": advocates,
            "advocate": advocates[0] if advocates else None,
            "submitted_at": _local_date(case.filed_at),
            "status": case.status,
        }
    return summaries


def _case_titles(cases):
    """Return the court's *Edit case title* names, by case id, one query per case type."""
    by_type = defaultdict(list)
    for case in cases:
        by_type[case.case_type].append(case.pk)
    titles = {}
    for case_type, ids in by_type.items():
        model = get_config(case_type).get_detail_model()
        for row in model.objects.filter(case_id__in=ids).only("case_id", "additional_details"):
            if title := row.additional_details.get("case_title"):
                titles[row.case_id] = title
    return titles


def get_case_summary(case):
    """Return the list-row facts of one case."""
    return get_case_summaries([case.pk])[case.pk]


def get_filing_view(case, catalogue):
    """Return the filed values by section and record, each with the document it was read from."""
    groups = defaultdict(dict)
    for field in catalogue.values():
        _field_id, index = ports.split_ref(field.ref)
        if index is None:
            title = ports.SECTIONS[field.section]
        else:
            title = f"{RECORD_TITLES.get(field.section, field.section)} {index + 1}"
        groups[field.section].setdefault(title, []).append(
            {
                "ref": field.ref,
                "label": field.label,
                "value": field.value,
                "source_document_id": field.document_id,
            }
        )
    return [
        {
            "id": section,
            "title": title,
            "groups": [
                {"title": group, "fields": fields} for group, fields in groups[section].items()
            ],
        }
        for section, title in ports.SECTIONS.items()
        if section in groups
    ]


def get_bundle(case):
    """Return the numbered case bundle: generated documents first (none yet), then uploads."""
    documents = CaseDocument.objects.active().filter(case=case).order_by("created_at")
    return [
        {
            "no": number,
            "kind": "SCAN",
            "name": document.get_document_type_display(),
            "document_id": document.pk,
            "poor_scan": bool(document.additional_details.get("poor_scan")),
        }
        for number, document in enumerate(documents, start=1)
    ]


def checklist(case):
    """Return the *What to check* items; display only."""
    return list(CHECKLIST)


def _evidence(case):
    records = defaultdict(dict)
    for item in CaseEvidence.objects.active().filter(case=case).select_related("case_document"):
        records[item.ordinal][item.evidence_type] = item.evidence_info
    return [records[ordinal] for ordinal in sorted(records)]


def _date(value):
    return datetime.date.fromisoformat(value) if value else None


def _cheque_valid_until(cheque_date):
    return ports.add_months(cheque_date, CHEQUE_VALIDITY_MONTHS) - datetime.timedelta(days=1)


def check_facts(case, today):
    """Return the ``CHECKS`` rule input (#2.4): legal facts computed here, never by the rule."""
    records = _evidence(case)
    cheques = []
    for index, record in enumerate(records):
        cheque = record.get(EvidenceType.CHEQUE, {})
        memo = record.get(EvidenceType.RETURN_MEMO, {})
        cheque_date = _date(cheque.get("cheque_date"))
        cheques.append(
            {
                "index": index,
                "cheque_date": cheque.get("cheque_date"),
                "presented_on": memo.get("presentation_date"),
                "valid_until": cheque_date and _cheque_valid_until(cheque_date).isoformat(),
                "returned_on": memo.get("return_date"),
                "amount": cheque.get("amount"),
                "return_reason": memo.get("return_reason"),
            }
        )
    notice = records[0].get(EvidenceType.LEGAL_DEMAND_NOTICE, {}) if records else {}
    uploaded = set(
        CaseDocument.objects.active().filter(case=case).values_list("document_type", flat=True)
    )
    complainant = (
        CaseParticipant.objects.active()
        .filter(case=case, role=ParticipantRole.COMPLAINANT)
        .select_related("institution")
        .order_by("ordinal")
        .first()
    )
    institution = complainant.institution if complainant else None
    jurisdiction = getattr(ports.detail(case), "jurisdiction_limitation", {}) or {}
    return {
        "case_type": case.case_type,
        "today": today.isoformat(),
        "cheques": [{k: v for k, v in cheque.items() if v is not None} for cheque in cheques],
        "notice": {
            "dispatched_on": notice.get("dispatch_date"),
            "served_on": notice.get("delivery_date"),
            "delivered": bool(notice.get("is_delivered")),
            "postal_receipt_uploaded": DocumentType.PROOF_OF_DISPATCH in uploaded,
            "delivery_proof_uploaded": DocumentType.PROOF_OF_DELIVERY_OF_DEMAND_NOTICE in uploaded,
        },
        "cause_of_action_on": jurisdiction.get("cause_of_action_date"),
        "filed_on": (_local_date(case.filed_at) or today).isoformat(),
        "delay_applicable": ports.delay_applicable(case, today),
        "delay_prayer_present": ports.delay_prayer_present(case),
        "complainant_is_institution": institution is not None,
        "complainant_cin_or_pan_present": bool(
            institution and (institution.cin or institution.pan)
        ),
    }
