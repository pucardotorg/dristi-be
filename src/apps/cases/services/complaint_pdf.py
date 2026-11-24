"""The e-filing complaint PDF: preview, and the copy every signer signs (efiling.md §16).

``render_preview`` renders the complaint from the stored case on every call
and stores nothing ("always current", §16). ``get_or_create_signing_package``
renders it once per signing round, appends every uploaded document after a
"Documents uploaded by the Complainant." page (``DOC-07``), and stores the
result: the one file the case's signers sign, each on top of the previous
signer's copy (signing-methods ``SGM-03``, ``SGM-07``). The signature block
leaves one slot per signatory, two to a row (``DOC-02``), and the renderer
reports where each box landed, so each signature is placed on its own box.

Data comes from the case preview (``filing.preview_data``) -- the case's own
frozen copies -- never from the client. The template is ``PDFTemplate(key="case-complaint")``, seeded
from ``data/seed/core/pdf``.
"""

import io
import json

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from apps.api.errors import BusinessError
from apps.files.services import FileNotFound, get_file, get_file_content
from apps.parties.models import EntityType, Gender
from apps.pdf import errors as pdf_errors
from apps.pdf.exceptions import PDFError, PDFRenderError
from apps.pdf.renderer import fonts
from apps.pdf.renderer.merge import merge, page_count
from apps.pdf.services import jobs as pdf_jobs
from apps.pdf.services.config_loader import PDFConfigLoader
from apps.pdf.services.context import RequestContext
from apps.pdf.services.documents import delete_documents, store_document, tags_for
from apps.pdf.services.generator import document_filename, render_document_with_anchors

from .. import errors
from ..models import (
    SIGNING_ROLES,
    Case,
    CaseParticipant,
    CaseStatus,
    ComplaintSigningPackage,
    ParticipantRole,
    SigningPackageStatus,
)
from . import richtext
from .case_types import (
    CaseType,
    DocumentType,
    ModeOfService,
    NatureOfDebt,
    NonDeliveryReason,
    PaymentStatus,
    ReturnReason,
)
from .filing import (
    _raise_not_ready,
    get_filing_side_case,
    get_viewable_case,
    preview_data,
    validation_errors,
)
from .services import lock_case
from .signing import signer_q

TEMPLATE_KEY = "case-complaint"
APPENDIX_HEADING = "Documents uploaded by the Complainant."
# Where the sample places it: the complaint's left margin, near the top.
APPENDIX_MARGIN = 57
APPENDIX_TOP = 72

# The cover's "Complaint under ..." line prints the case type's long title (DOC-03).
LONG_TITLES = {
    CaseType.CHEQUE_BOUNCE: "Section 138 of the Negotiable Instruments Act, 1881",
}

# The Documents screen's order (efiling §14, DCM-1 … DCM-13), which the list of
# documents and the appended files follow (print §3.2, DOC-07).
DOCUMENT_ORDER = (
    DocumentType.BOUNCED_CHEQUE,
    DocumentType.RETURN_MEMO,
    DocumentType.LEGAL_DEMAND_NOTICE,
    DocumentType.PROOF_OF_DISPATCH,
    DocumentType.PROOF_OF_DELIVERY_OF_DEMAND_NOTICE,
    DocumentType.REPLY_TO_DEMAND_NOTICE,
    DocumentType.PROOF_OF_DEBT,
    DocumentType.PROOF_OF_TRANSACTION,
    DocumentType.IDENTITY_PROOF,
    DocumentType.POA_DOCUMENT,
    DocumentType.VAKALATNAMA,
    DocumentType.AFFIDAVIT,
    DocumentType.OTHER_SUPPORTING_DOCUMENT,
)
# Printed names where the PRD's differs from the stored type's label (DCM-9/10).
DOCUMENT_NAMES = {
    DocumentType.BOUNCED_CHEQUE: "Cheque",
    DocumentType.RETURN_MEMO: "Cheque return memo",
    DocumentType.IDENTITY_PROOF: "ID Card",
    DocumentType.POA_DOCUMENT: "Power of Attorney Authorisation",
}
ROLE_NAMES = {
    ParticipantRole.COMPLAINANT: "Complainant",
    ParticipantRole.POA_HOLDER: "PoA holder",
    ParticipantRole.ACCUSED: "Accused",
}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


# Payload


def build_payload(case):
    """Return the template's data: the case preview plus the ``extras`` it prints.

    The caller has already checked access to ``case``. The preview is the
    cached assembly ``GET /cases/{id}`` returns, cleared on every write.
    """
    data = json.loads(json.dumps(preview_data(case), cls=DjangoJSONEncoder))
    case = Case.objects.select_related("court").get(pk=case.pk)
    participants = data["participants"]
    complainants = [p for p in participants if p["role"] == ParticipantRole.COMPLAINANT]
    accused = [p for p in participants if p["role"] == ParticipantRole.ACCUSED]
    complainant_label = {
        p["case_participant_id"]: f"Complainant {p['ordinal']}" for p in complainants
    }

    data["documents"] = _ordered_documents(data, complainant_label)
    data["signatories"] = signatories(data, complainant_label)
    data["extras"] = {
        "court_name": case.court.name if case.court_id else "-",
        "case_type_long_title": LONG_TITLES.get(case.case_type, case.get_case_type_display()),
        "case_title": f"{_side_title(complainants)} v/s {_side_title(accused)}",
        "case_ref": case.case_number or case.filing_number or f"Draft {str(case.pk)[:8]}",
        "complainant_label": complainant_label,
        "labels": _labels(),
        "rich_text": _rich_text(data),
    }
    return data


def signatories(data, complainant_label):
    """Return one ``{key, name, label}`` per required signer, in signing-block order.

    The signers the filing records (``SIGNING_ROLES``): each complainant, then
    each POA holder, labelled with whom they sign for (``DOC-02``).
    """
    represented = {}
    for mandate in data.get("poa_mandates", []):
        label = complainant_label.get(mandate["represented_participant_id"])
        if label:
            represented.setdefault(mandate["poa_participant_id"], []).append(label)
    rows = []
    for role in SIGNING_ROLES:
        for p in data["participants"]:
            if p["role"] != role:
                continue
            if role == ParticipantRole.POA_HOLDER:
                label = "PoA holder for " + ", ".join(represented.get(p["case_participant_id"], []))
            else:
                label = complainant_label[p["case_participant_id"]]
            name = p["name_at_filing"] or p.get("entity_name_at_filing") or "-"
            rows.append({"key": p["case_participant_id"], "name": name, "label": label})
    return rows


def _side_title(parties):
    """The first party's full name, with "+N other(s)" for the rest (DOC-03)."""
    if not parties:
        return "-"
    first = parties[0]
    name = first.get("entity_name_at_filing") or first["name_at_filing"] or "-"
    others = len(parties) - 1
    if others:
        name += f" +{others} other{'s' if others > 1 else ''}"
    return name


def _ordered_documents(data, complainant_label):
    """The active documents in Documents-screen order, each with its printed name.

    A document that repeats carries its record: its evidence item's number for
    a scan, its party for an ID card, POA document or vakalatnama.
    """
    evidence_number = {}
    for item in data["evidence"]:
        if item.get("case_document_id"):
            evidence_number[item["case_document_id"]] = item["ordinal"]
        evidence_number[item["case_evidence_id"]] = item["ordinal"]
    party = {
        p["case_participant_id"]: complainant_label.get(p["case_participant_id"])
        or f"{ROLE_NAMES.get(p['role'], p['role'])} {p['ordinal']}"
        for p in data["participants"]
    }
    rank = {code: index for index, code in enumerate(DOCUMENT_ORDER)}
    documents = sorted(
        data["documents"],
        key=lambda d: (rank.get(d["document_type"], len(rank)), d["created_at"]),
    )
    counts = {}
    for document in documents:
        code = document["document_type"]
        name = DOCUMENT_NAMES.get(code) or DocumentType(code).label
        number = evidence_number.get(document["case_document_id"]) or evidence_number.get(
            document.get("case_evidence_id")
        )
        if document.get("case_participant_id") in party:
            name = f"{name} - {party[document['case_participant_id']]}"
        elif number:
            name = f"{name} {number}"
        else:
            counts[code] = counts.get(code, 0) + 1
            name = f"{name} {counts[code]}"
        document["label"] = document.get("display_name") or name
    return documents


def _labels():
    """Display labels for every coded value the complaint prints (DOC-05)."""
    return {
        "gender": dict(Gender.choices),
        "entity_type": dict(EntityType.choices),
        "return_reason": dict(ReturnReason.choices),
        "nature_of_debt": dict(NatureOfDebt.choices),
        "mode_of_service": dict(ModeOfService.choices),
        "non_delivery_reason": dict(NonDeliveryReason.choices),
        "payment_status": dict(PaymentStatus.choices),
        "adr": {"YES": "Yes", "NO": "No", "MAYBE": "Maybe"},
    }


def _rich_text(data):
    """Editor HTML fields as safe paragraphs; ``["-"]`` for one left empty (DOC-01)."""
    prayer = data["details"].get("adr_other_prayer") or {}

    def paragraphs(html):
        return richtext.to_paragraphs(html) or ["-"]

    return {
        "affidavit": paragraphs(data.get("affidavit")),
        "interim_relief": paragraphs(prayer.get("interim_relief")),
        "final_relief": paragraphs(prayer.get("final_relief")),
        "pip_affidavit": {
            p["case_participant_id"]: paragraphs(p.get("party_in_person_affidavit"))
            for p in data["participants"]
            if p["role"] == ParticipantRole.COMPLAINANT
        },
    }


def _tenant_id():
    return settings.CASE_PDF_TENANT_ID


def _require_complete(case):
    """Refuse the complaint PDF until the filing passes the completeness check (§5)."""
    problems = validation_errors(case)
    if problems:
        _raise_not_ready(errors.FILING_INCOMPLETE, problems)


# Preview


def render_preview(case_id, user):
    """Return the complaint PDF for ``user``'s view of the case.

    A draft is rendered from the case on every call and nothing is stored
    ("always current", §16). Once the case has moved to signing, the PDF is
    the one being signed: the latest signing package's current file -- the
    complaint with its documents and every signature recorded so far -- so
    what is shown is exactly what was, or is being, signed. A case pending
    signature whose package is not prepared yet is still rendered.
    """
    case = get_viewable_case(case_id, user)
    if case.status != CaseStatus.DRAFT_IN_PROGRESS:
        signed = current_signing_file(case)
        if signed is not None:
            return signed
    _require_complete(case)
    payload = build_payload(case)
    try:
        return pdf_jobs.render_sync(TEMPLATE_KEY, _tenant_id(), payload, user=user)
    except PDFError as exc:
        raise pdf_errors.api_error(exc) from exc


def current_signing_file(case):
    """Return the bytes of ``case``'s latest signing package's current file, or ``None``.

    The latest package that is not superseded: open while it is being signed,
    complete once everyone has signed. Its current file carries every
    signature recorded on it.
    """
    package = (
        ComplaintSigningPackage.objects.filter(case=case)
        .exclude(status=SigningPackageStatus.SUPERSEDED)
        .order_by("-signing_round")
        .first()
    )
    if package is None or package.current_file_id is None:
        return None
    try:
        with get_file_content(str(package.current_file_id)) as handle:
            return handle.read()
    except FileNotFound as exc:
        raise BusinessError(
            pdf_errors.NO_DOCUMENT, "The signed complaint PDF no longer exists."
        ) from exc


# The copy to sign


def get_signing_package(case_id, user):
    """Return the case's open signing package, or ``None``.

    Readable by the filing side and by anyone who signs as one of the case's
    signatories (``signing.signer_q``): a complainant with no account yet signs
    from their own device by the number entered for them (efiling §18), and
    needs the package -- its file and their placeholder -- to start the e-sign.
    """
    signs_here = Case.objects.filter(
        pk__in=CaseParticipant.objects.active().filter(signer_q(user)).values("case_id")
    )
    case = signs_here.filter(pk=case_id).first() or get_filing_side_case(case_id, user)
    return case, open_package(case)


def open_package(case):
    """Return the case's ``OPEN`` signing package, or ``None``."""
    return ComplaintSigningPackage.objects.filter(
        case=case, status=SigningPackageStatus.OPEN
    ).first()


def get_or_create_signing_package(case_id, user):
    """Return ``(package, created)``: the complaint PDF this signing round signs.

    Only while the case is ``PENDING_SIGN``. The first call of a round renders
    the complaint, appends every uploaded document and stores the result; every
    later call returns that same package, so all signers sign the same bytes.
    The case row is locked, so concurrent calls create one package.
    """
    case = get_filing_side_case(case_id, user)
    with transaction.atomic():
        case = lock_case(case)
        if case.status != CaseStatus.PENDING_SIGN:
            raise BusinessError(
                errors.INVALID_STATUS_TRANSITION,
                f"The complaint PDF to sign is prepared only while the case is "
                f"{CaseStatus.PENDING_SIGN}; this one is {case.status}.",
            )
        existing = open_package(case)
        if existing is not None:
            return existing, False
        _require_complete(case)
        try:
            package = _build_package(case, user)
        except PDFError as exc:
            # The template, renderer or file storage failed: the standard PDF codes.
            raise pdf_errors.api_error(exc) from exc
    return package, True


def _build_package(case, user):
    """Render, append, store and record the signing package for a new round."""
    payload = build_payload(case)
    config = PDFConfigLoader.load(TEMPLATE_KEY)[2]
    context = RequestContext(
        tenant_id=_tenant_id(),
        key=TEMPLATE_KEY,
        entity_id=str(case.pk),
        user_id=str(user.pk),
    )
    complaint, anchors = render_document_with_anchors(config, payload, context)

    documents = payload["documents"]
    appended = [complaint, _appendix_page(), *(_as_pdf(d) for d in documents)]
    try:
        signing_bytes = merge(appended)
    except PDFRenderError as exc:
        raise BusinessError(errors.DOCUMENT_NOT_APPENDABLE) from exc
    if len(signing_bytes) > _max_signing_bytes():
        raise BusinessError(errors.SIGNING_FILE_TOO_LARGE)

    filename = document_filename(config, {"data": payload, "meta": context.as_dict()})
    tags = tags_for(TEMPLATE_KEY, str(case.pk))
    stored = []
    try:
        complaint_id = store_document(complaint, filename=filename, user_id=user.pk, tags=tags)
        stored.append(complaint_id)
        signing_id = store_document(
            signing_bytes,
            filename=filename.replace(".pdf", "-with-documents.pdf"),
            user_id=user.pk,
            tags=tags,
        )
        stored.append(signing_id)
        last_round = (
            ComplaintSigningPackage.objects.filter(case=case)
            .order_by("-signing_round")
            .values_list("signing_round", flat=True)
            .first()
        )
        package = ComplaintSigningPackage.objects.create(
            case=case,
            signing_round=(last_round or 0) + 1,
            complaint_file_id=complaint_id,
            signing_file_id=signing_id,
            current_file_id=signing_id,
            page_count=page_count(signing_bytes),
            affidavit_page=max((a["page"] for a in anchors.values()), default=0),
            signatories=payload["signatories"],
            placeholders=anchors,
            document_ids=[d["case_document_id"] for d in documents],
            created_by=user,
            updated_by=user,
        )
    except Exception:
        # The package row rolls back with the transaction; stored bytes do not.
        delete_documents(stored)
        raise
    return package


def _max_signing_bytes():
    """The largest signing file the storage and signing limits all accept."""
    return min(
        settings.FILE_MAX_SIZE_BYTES,
        settings.FILE_MAX_READ_BYTES,
        settings.PDF_MAX_SIGN_INPUT_BYTES,
    )


def _appendix_page():
    """The page that opens the appended documents (DOC-07).

    As in the efiling §16.9 sample: the heading in the complaint's own bold
    face, at the top left of the page.
    """
    fonts.register_family(fonts.DEFAULT_FONT)
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=A4, invariant=1)
    canvas.setFont(fonts.face_name(fonts.DEFAULT_FONT, "bold"), 10.5)
    canvas.drawString(APPENDIX_MARGIN, A4[1] - APPENDIX_TOP, APPENDIX_HEADING)
    canvas.showPage()
    canvas.save()
    return out.getvalue()


def _as_pdf(document):
    """Return the uploaded document as PDF bytes, unchanged when it is a PDF.

    An image becomes one A4 page, fitted inside the margins. A format that
    cannot be put into a PDF (HEIC) or a file that cannot be read is refused,
    naming the document, so the filer can replace it.
    """
    try:
        content_type = get_file(document["document_id"])["content_type"].split(";")[0].lower()
        with get_file_content(document["document_id"]) as handle:
            content = handle.read()
    except FileNotFound as exc:
        raise _not_appendable(document) from exc
    if content_type == "application/pdf":
        return content
    if content_type in IMAGE_TYPES:
        try:
            return _image_page(content)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise _not_appendable(document) from exc
    raise _not_appendable(document)


def _not_appendable(document):
    return BusinessError(
        errors.DOCUMENT_NOT_APPENDABLE,
        f"{document['label']} cannot be added to the complaint PDF; upload it as a PDF, "
        "JPEG or PNG.",
        field=f"documents.{document['case_document_id']}",
    )


def _image_page(content):
    """Place an image on one A4 page, scaled to fit inside 36 pt margins."""
    margin = 36
    with Image.open(io.BytesIO(content)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        scale = min((A4[0] - 2 * margin) / width, (A4[1] - 2 * margin) / height, 1.0)
        drawn_w, drawn_h = width * scale, height * scale
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=A4, invariant=1)
    canvas.drawImage(
        ImageReader(io.BytesIO(buffer.getvalue())),
        (A4[0] - drawn_w) / 2,
        (A4[1] - drawn_h) / 2,
        drawn_w,
        drawn_h,
    )
    canvas.showPage()
    canvas.save()
    return out.getvalue()


def superseded_file_ids(package):
    """Every file a superseded package produced: the rendered ones and each signed copy.

    The signed copies form a chain from ``signing_file``: each transaction
    signed the previous one's output, so the chain is followed from there and
    copies of other rounds are left alone.
    """
    from apps.esign.constants import EntityType
    from apps.esign.models import ESignTransaction

    signed = dict(
        ESignTransaction.objects.filter(
            entity_type=EntityType.CASE_FILING.value, entity_id=str(package.case_id)
        )
        .exclude(signed_file_id="")
        .values_list("source_file_id", "signed_file_id")
    )
    ids = [
        str(file_id) for file_id in (package.complaint_file_id, package.signing_file_id) if file_id
    ]
    current = ids[-1] if package.signing_file_id else None
    while current in signed and signed[current] not in ids:
        current = signed[current]
        ids.append(current)
    return list(dict.fromkeys(ids))
