"""Step 1, drafting (spec 0033 #6.1-#6.6, #6.5a, #6.5b).

A draft saves anything with the right shape (``ALC-27``); completeness is
checked only at *Proceed to sign*. Every write here is by the drafting circle,
in ``DRAFT`` (documents, edits) or before submission (delete), with the
application locked and ``If-Match`` checked.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.cases.models import Case
from apps.files.documents import (
    ACCEPTED_FORMATS,
    discard_documents,
    document_error,
    store_documents,
)
from apps.hearings import selectors as hearings
from apps.payments.enums import OPEN_PAYMENT_STATUSES
from apps.payments.models import Demand, PaymentDemandItem
from apps.payments.services.demands import DemandService
from apps.pdf import errors as pdf_errors
from apps.pdf.exceptions import PDFError

from .. import access, conf, errors, ports
from ..enums import ApplicationStatus
from ..models import Application, ApplicationDocument, ApplicationType
from ..types import registry
from ..types.base import FieldProblem, FilerContext
from . import common, rendering, richtext
from .calendar import today
from .common import Action

logger = logging.getLogger(__name__)

S = ApplicationStatus


# Problems -> one API error ----------------------------------------------------------


def raise_problems(problems):
    """Raise every problem as one ``400`` with an item per path, each with its code (#15.6)."""
    if not problems:
        return
    detail = {}
    for problem in problems:
        detail.setdefault(problem.field, []).append(ErrorDetail(problem.message, code=problem.code))
    raise ValidationError(detail)


# Case and caller --------------------------------------------------------------------


def _case(case_id):
    case = Case.objects.select_related("court").filter(pk=case_id).first()
    if case is None:
        raise NotFound("Case not found.")
    return case


def filer_context(case_id, user):
    return FilerContext(case_id=case_id, user=user, access=ports.case_access(case_id, user))


def _require_on_file(case):
    if not ports.is_on_file(case):
        raise BusinessError(errors.CASE_NOT_ON_FILE)


def _require_drafter(ctx):
    if not ctx.access.is_drafter:
        raise BusinessError(errors.CANNOT_DRAFT)


# #6.1 Offering types ----------------------------------------------------------------


def available_types(case_id, user):
    """``(can_raise, [(type, suggested)])`` for the caller (``ALC-26``, #6.1, #6.5c)."""
    case = _case(case_id)
    ctx = filer_context(case_id, user)
    if not ctx.access.is_case_reader:
        raise NotFound("Case not found.")
    if not ctx.access.is_drafter or not ports.is_on_file(case):
        return False, []
    suggested = set(conf.suggested_by_stage().get(_stage_key(case), [])[:3])
    offered = []
    for row in ApplicationType.objects.active().order_by("sequence", "code"):
        spec = registry.get(row.code)
        if spec is None or spec.unavailable_reason(ctx) is not None:
            continue
        offered.append((row, row.code in suggested))
    return True, offered


def _stage_key(case):
    """The case's current stage key; stages are not modelled yet (``CaseSummary.stage``)."""
    return ""


def _available_type(ctx, code):
    row = ApplicationType.objects.active().filter(code=code).first()
    spec = registry.get(code) if row else None
    if spec is None or spec.unavailable_reason(ctx) is not None:
        raise BusinessError(errors.TYPE_NOT_AVAILABLE, field="application_type")
    return row


# #6.2 Form context ------------------------------------------------------------------


def form_context(case_id, code, user):
    """Everything the form needs that the filer does not type (#6.2)."""
    case = _case(case_id)
    _require_on_file(case)
    ctx = filer_context(case_id, user)
    _require_drafter(ctx)
    row = _available_type(ctx, code)
    options = ports.advocate_options(case_id, ctx.side)
    return {
        "type": row,
        "raised_by_options": [
            {
                "user_id": option.user_id,
                "name": option.name,
                "kind": option.kind,
                "litigants": [_litigant(case_id, pid) for pid in option.litigant_ids],
            }
            for option in options
        ],
        "defaults": defaults(ctx, options),
        "system_fields": row.spec.form_context(ctx),
    }


def _litigant(case_id, participant_id):
    party = ports.participant(case_id, participant_id)
    return {
        "participant_id": participant_id,
        "name": (party.name_at_filing or party.entity_name_at_filing) if party else "",
        "role": party.role if party else "",
    }


def defaults(ctx, options):
    """*Raised by* and *Litigant* preselection (#3.3)."""
    if ctx.access.is_advocate_or_pip:
        own = next((o for o in options if o.user_id == ctx.user.pk), None)
        litigants = own.litigant_ids if own else ()
    elif len(ctx.access.works_for) == 1:
        own = next((o for o in options if o.user_id == ctx.access.works_for[0]), None)
        litigants = own.litigant_ids if own else ()
    else:
        return {"raised_by": None, "litigant": None}
    return {
        "raised_by": own.user_id if own else None,
        "litigant": litigants[0] if len(litigants) == 1 else None,
    }


# #6.3 Create and edit ---------------------------------------------------------------


def _check_parties(application, ctx, *, raised_by_given, litigant_given):
    """*Raised by* and *Litigant* against the side's options (``E13005``, ``E13006``)."""
    options = ports.advocate_options(application.case_id, application.side)
    option = None
    if application.raised_by_id:
        option = next((o for o in options if o.user_id == application.raised_by_id), None)
        if option is None:
            raise BusinessError(errors.RAISED_BY_INVALID, field="raised_by")
    if application.raised_on_behalf_of:
        party = ports.participant(application.case_id, application.raised_on_behalf_of)
        if party is None or ports.LITIGANT_SIDE[party.role] != application.side:
            raise BusinessError(errors.LITIGANT_INVALID, field="litigant")
        if option is not None and party.pk not in option.litigant_ids:
            if litigant_given or not raised_by_given:
                raise BusinessError(errors.LITIGANT_INVALID, field="litigant")
            # A new Raised by who does not represent the chosen litigant clears it (#3.3).
            application.raised_on_behalf_of = None


def _apply_fields(application, data):
    if "details" in data:
        details = richtext.sanitise(data["details"] or "")
        if len(details.encode()) > conf.details_max_bytes():
            raise BusinessError(api_errors.MAX_LENGTH, field="details")
        application.details = details
    if "data" in data:
        application.data = dict(data["data"] or {})
        application.data.pop("changes", None)  # computed at Proceed to sign (#3.4)


def _validate_draft(application):
    """Shape and partial rules: drafts always save, but not with wrong values (#3.2)."""
    spec = application.spec
    problems = spec.schema_problems(application.data)
    if problems:
        raise_problems(problems)
    raise_problems(spec.validate(application, complete=False))
    raise_problems(_document_problems(application))


def _document_problems(application):
    """Every referenced document is this application's, on that path (``E13011``)."""
    if application._state.adding:
        attached = {}
    else:
        attached = dict(application.documents.values_list("id", "field_path"))
    problems = []
    for path, document_id in application.spec.document_refs(application.data):
        field_path = path.removeprefix("data.")
        if attached.get(_uuid(document_id)) != field_path:
            problems.append(
                FieldProblem(
                    path,
                    errors.DOCUMENT_NOT_ON_APPLICATION.code,
                    errors.DOCUMENT_NOT_ON_APPLICATION.message,
                )
            )
    return problems


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def apply_initial_fields(application, ctx, data):
    """Set and check a new application's fields (#6.3 steps 2-3); raises on bad input."""
    application.raised_by_id = data.get("raised_by")
    application.raised_on_behalf_of = data.get("litigant")
    _apply_fields(application, data)
    if application.raised_on_behalf_of:
        party = ports.participant(application.case_id, application.raised_on_behalf_of)
        if party is not None and ports.LITIGANT_SIDE[party.role] != application.side:
            raise BusinessError(errors.LITIGANT_INVALID, field="litigant")
    _check_parties(
        application, ctx, raised_by_given="raised_by" in data, litigant_given="litigant" in data
    )
    if application.spec.needs_hearing:
        hearing = hearings.next_hearing(application.case_id)
        application.hearing_id = hearing.id if hearing else None
    _validate_draft(application)


def create(case_id, user, data):
    """``POST /cases/{case_id}/applications/`` (#6.3). Returns ``(application, created)``."""
    case = _case(case_id)
    _require_on_file(case)
    ctx = filer_context(case_id, user)
    _require_drafter(ctx)
    code = data["application_type"]
    if code == "OBJECTION" or data.get("objection_to"):
        if code != "OBJECTION" or not data.get("objection_to"):
            raise BusinessError(errors.TYPE_NOT_AVAILABLE, field="application_type")
        from .objections import start_objection

        return start_objection(data["objection_to"], user, case_id=case_id, data=data)
    row = _available_type(ctx, code)
    application = Application(
        case=case,
        application_type=row,
        status=S.DRAFT,
        side=ctx.side,
        created_by=user,
        updated_by=user,
    )
    apply_initial_fields(application, ctx, data)
    with transaction.atomic():
        application.save()
        common.log(application, Action.CREATE, user, from_status="", to_status=S.DRAFT)
    logger.info("event=APPLICATION_CREATED application_id=%s type=%s", application.pk, code)
    return application, True


def _filer_locked(application_id, user, action, version):
    application = common.lock(application_id)
    if not access.can_see(application, user):
        raise NotFound("Application not found.")
    common.require(application, action)
    if not access.in_drafting_circle(application, user):
        raise BusinessError(errors.CANNOT_DRAFT)
    common.require_version(application, version)
    return application


def update(application_id, user, data, *, version=None):
    """``PATCH /applications/{id}/`` (#6.3). Draft only, drafting circle, ``If-Match``."""
    with transaction.atomic():
        application = _filer_locked(application_id, user, Action.EDIT, version)
        ctx = filer_context(application.case_id, user)
        if "raised_by" in data:
            application.raised_by_id = data["raised_by"]
        if "litigant" in data:
            application.raised_on_behalf_of = data["litigant"]
            party = (
                ports.participant(application.case_id, data["litigant"])
                if data["litigant"]
                else None
            )
            if party is not None and ports.LITIGANT_SIDE[party.role] != application.side:
                raise BusinessError(errors.LITIGANT_INVALID, field="litigant")
        _apply_fields(application, data)
        _check_parties(
            application, ctx, raised_by_given="raised_by" in data, litigant_given="litigant" in data
        )
        _validate_draft(application)
        common.transition(application, Action.EDIT, user)
    return application


# #6.4 Documents ----------------------------------------------------------------------


def add_document(application_id, user, upload, *, name="", field_path="", version=None):
    """Attach a file (#6.4); return the ``ApplicationDocument``."""
    with transaction.atomic():
        application = _filer_locked(application_id, user, Action.EDIT, version)
        spec = application.spec
        field_path = (field_path or "").removeprefix("data.")
        if field_path:
            if not spec.declares_document_field(field_path):
                raise BusinessError(errors.DOCUMENT_NOT_ON_APPLICATION, field="field_path")
            name = spec.document_label(field_path)
        elif not (name or "").strip():
            raise BusinessError(api_errors.REQUIRED, field="name")
        formats = ACCEPTED_FORMATS
        if spec.document_formats:
            formats = {k: v for k, v in ACCEPTED_FORMATS.items() if k in spec.document_formats}
        problem = document_error(upload, formats)
        if problem:
            raise BusinessError(errors.DOCUMENT_NOT_ACCEPTED, f"The file {problem}", field="file")
        try:
            file_ids = store_documents(
                [upload],
                user_id=user.pk,
                tags=["applications", str(application.pk)],
            )
        except DjangoValidationError as exc:
            raise BusinessError(errors.DOCUMENT_NOT_ACCEPTED, field="file") from exc
        try:
            document = ApplicationDocument.objects.create(
                application=application,
                field_path=field_path,
                name=name.strip()[:255],
                file_id=file_ids[0],
                sequence=application.documents.count(),
                created_by=user,
                updated_by=user,
            )
            common.transition(application, Action.EDIT, user)
        except Exception:
            discard_documents(file_ids)
            raise
    return document


def remove_document(application_id, document_id, user, *, version=None):
    """Remove a file the draft no longer references (#6.4, ``E13012``)."""
    with transaction.atomic():
        application = _filer_locked(application_id, user, Action.EDIT, version)
        document = application.documents.filter(pk=document_id).first()
        if document is None:
            raise NotFound("Document not found.")
        used = {_uuid(doc_id) for _, doc_id in application.spec.document_refs(application.data)}
        if document.pk in used:
            raise BusinessError(errors.DOCUMENT_IN_USE)
        file_id = document.file_id
        document.delete()
        common.transition(application, Action.EDIT, user)
        transaction.on_commit(lambda: discard_documents([file_id]))


# #6.5 Proceed to sign ----------------------------------------------------------------


def completeness_problems(application):
    """Every gap, each on its path (``E13008``, #6.5 step 1)."""
    problems = []
    for field_name, value in (
        ("raised_by", application.raised_by_id),
        ("litigant", application.raised_on_behalf_of),
    ):
        if not value:
            problems.append(
                FieldProblem(
                    field_name,
                    errors.APPLICATION_INCOMPLETE.code,
                    errors.APPLICATION_INCOMPLETE.message,
                )
            )
    if not richtext.has_text(application.details):
        problems.append(
            FieldProblem("details", errors.DETAILS_REQUIRED.code, errors.DETAILS_REQUIRED.message)
        )
    problems.extend(application.spec.validate(application, complete=True))
    problems.extend(_document_problems(application))
    return problems


def require_hearing_upcoming(application):
    """Advance / Postpone: still the case's next scheduled hearing, not past (``E13016``)."""
    if not application.spec.needs_hearing:
        return
    upcoming = hearings.next_hearing(application.case_id)
    if upcoming is None or upcoming.id != application.hearing_id or upcoming.hearing_date < today():
        raise BusinessError(errors.HEARING_NOT_UPCOMING)


def require_target_pending(application):
    """An objection's target is still undecided (``E13023``)."""
    if application.is_objection and application.objection_to.status not in (
        S.PENDING_REVIEW,
        S.PENDING_DECISION,
    ):
        raise BusinessError(errors.TARGET_NOT_PENDING)


def proceed_to_sign(application_id, user, *, version=None):
    """``POST /applications/{id}/proceed-to-sign/`` (#6.5)."""
    with transaction.atomic():
        application = _filer_locked(application_id, user, Action.PROCEED_TO_SIGN, version)
        raise_problems(completeness_problems(application))
        require_hearing_upcoming(application)
        require_target_pending(application)
        application.spec.prepare(application)
        try:
            file_id, _ = rendering.render_and_store(application, user)
        except PDFError as exc:
            raise pdf_errors.api_error(exc) from exc
        application.signing_file_id = file_id
        common.transition(application, Action.PROCEED_TO_SIGN, user, to_status=S.PENDING_SIGNATURE)
        ports.tasks.open("sign_application", application, users=[application.raised_by_id])
        from . import notifications

        notifications.pending_signature(application)
    return application


def back_to_draft(application_id, user, *, version=None):
    """``POST /applications/{id}/back-to-draft/`` (#6.6, ``ALC-31``)."""
    with transaction.atomic():
        application = _filer_locked(application_id, user, Action.BACK_TO_DRAFT, version)
        application.signing_file_id = ""
        common.transition(application, Action.BACK_TO_DRAFT, user, to_status=S.DRAFT)
        ports.tasks.expire("sign_application", application, reason="BACK_TO_DRAFT")
    return application


# #6.5b Delete -----------------------------------------------------------------------


def delete(application_id, user, *, version=None):
    """``DELETE /applications/{id}/`` before submission (#6.5b, ``ALC-39``)."""
    with transaction.atomic():
        application = _filer_locked(application_id, user, Action.DELETE, version)
        demand = (
            Demand.objects.filter(pk=application.demand_id).first()
            if application.demand_id
            else None
        )
        if demand is not None:
            if PaymentDemandItem.objects.filter(
                demand_item__demand=demand, payment__status__in=OPEN_PAYMENT_STATUSES
            ).exists():
                raise BusinessError(errors.PAYMENT_IN_FLIGHT)
            DemandService.cancel_demand(demand, reason="Application deleted", actor=user)
        common.log(
            application,
            Action.DELETE,
            user,
            from_status=application.status,
            to_status="",
        )
        for task in ("sign_application", "pay_application_fee"):
            ports.tasks.expire(task, application, reason="DELETED")
        file_ids = [*application.documents.values_list("file_id", flat=True)]
        file_ids += [f for f in (application.signing_file_id,) if f]
        application.delete()
        transaction.on_commit(lambda: discard_documents(file_ids))


# #6.5a Preview ----------------------------------------------------------------------


def preview(application_id, user):
    """The structure of #6.5a; in ``PENDING_SIGNATURE`` it names the stored file."""
    application = access.get_visible(application_id, user)
    if application.status not in (S.DRAFT, S.PENDING_SIGNATURE) or not access.in_drafting_circle(
        application, user
    ):
        raise NotFound("Application not found.")
    structure = rendering.build(application)
    structure["file_id"] = application.signing_file_id or None
    return application, structure


def preview_pdf(application_id, user):
    """The preview as PDF bytes; in ``PENDING_SIGNATURE`` exactly the stored copy (#6.5a)."""
    from apps.files.services import FileNotFound, get_file_content

    application, _ = preview(application_id, user)
    if application.signing_file_id:
        try:
            with get_file_content(application.signing_file_id) as handle:
                return application, handle.read()
        except FileNotFound as exc:
            raise BusinessError(pdf_errors.NO_DOCUMENT) from exc
    try:
        content, _ = rendering.render(application, user, draft=True)
    except PDFError as exc:
        raise pdf_errors.api_error(exc) from exc
    return application, content
