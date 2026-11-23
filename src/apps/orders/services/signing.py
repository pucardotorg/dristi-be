"""Signing: Aadhaar e-sign of one order or Roznama, the number and the date (#8).

``start_signing`` renders the page with its number, date and the signer's name,
stores it with ``apps.files`` and starts ``apps.esign``. The order learns of the
signature when the client confirms it (``record_signature``), checked against the
order's *current* signing file, so a signature begun before a move back, or on an
old Roznama text, can never be recorded. ``record_signed_file`` is the entry a
DSC module will call (open question 2): nothing in it is specific to e-sign.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.cases.selectors import get_case_summaries
from apps.esign.constants import ESignStatus
from apps.esign.errors import api_error as esign_api_error
from apps.esign.exceptions import ESignError
from apps.esign.models import ESignTransaction
from apps.esign.services import initiate_esign
from apps.hearings.services import calendar
from apps.pdf.services import documents as pdf_documents

from .. import conf, errors, ports, rendering, signals
from ..enums import NumberSeries, OrderStatus, RoznamaStatus, SigningMethod, TaskKey
from ..models import OrderRoznama
from . import common, diary, lifecycle, notifications, numbering

logger = logging.getLogger(__name__)
ENTITY_TYPE = "ORDER"
DEFAULT_DESIGNATION = "Magistrate"


def _require_method(method):
    """The method must be enabled for the state (``SGM-05``) and be one this endpoint can run.

    Only Aadhaar e-sign is started here. A DSC is made outside ``apps.esign`` and recorded
    with ``record_signed_file`` (open question 2), so enabling it in configuration does not
    make this endpoint start an e-sign for it.
    """
    if method not in conf.signing_methods() or method != SigningMethod.AADHAAR_ESIGN:
        raise BusinessError(errors.SIGNING_METHOD_NOT_ENABLED, field="method")


def _case_facts(order):
    from apps.hearings import selectors as hearing_selectors

    summary = get_case_summaries([order.case_id]).get(order.case_id)
    label = ""
    if order.next_hearing_purpose:
        label = diary.next_purpose_label(order)
    elif order.hearing_id:
        hearing = hearing_selectors.get_hearing(order.hearing_id)
        label = hearing.purpose_label if hearing else ""
    return {"case_summary": summary, "purpose_label": label}


def render_page_html(order):
    """The order page as HTML, for ``rendered_html`` (#5.3)."""
    return rendering.render_page(order, **_case_facts(order))


def _store(order, content, name, actor):
    return pdf_documents.store_document(
        content,
        filename=name,
        user_id=actor.pk,
        organization_id=order.court_id,
        tags=["order", str(order.pk)],
    )


def _initiate(order, actor, file_id):
    try:
        return initiate_esign(
            user=actor,
            module="orders",
            file_id=file_id,
            entity_type=ENTITY_TYPE,
            entity_id=str(order.pk),
            organization_id=order.court_id,
            sign_placeholder={
                **rendering.SIGN_PLACEHOLDER,
                "reason": "Order of the court",
                "signer_name": actor.name or "",
            },
        )
    except ESignError as exc:
        raise esign_api_error(exc) from exc


def start_signing(order_id, *, actor, method=SigningMethod.AADHAAR_ESIGN):
    """Prepare the PDF and start Aadhaar e-sign for one order (#8.1). Returns the e-sign form.

    Allots the number on the first attempt and sets the order date to the
    business date. The method must be enabled (``E14017``), and a held date must
    still be confirmable.
    """
    _require_method(method)
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "sign")
        lifecycle._validate_held_date(order)
        if not order.number:
            series = order.order_type.number_series
            order.number = numbering.allot(order, series)
        order.order_date = calendar.business_date()
        order.signer_designation = order.signer_designation or DEFAULT_DESIGNATION
        content = rendering.render_pdf(order, signing_user=actor, **_case_facts(order))
        order.signing_file_id = _store(order, content, f"order-{order.pk}.pdf", actor)
        common.save_order(order, actor, "signing started")
    return _initiate(order, actor, order.signing_file_id)


def _check_transaction(txn, actor, entity_id, signing_file_id):
    """The transaction must be a success, this order's, this user's and for the current file."""
    if (
        txn is None
        or txn.status != ESignStatus.SUCCESS
        or txn.entity_type != ENTITY_TYPE
        or txn.entity_id != str(entity_id)
        or txn.signer_id != actor.pk
        or not signing_file_id
        or txn.source_file_id != signing_file_id
    ):
        raise BusinessError(errors.SIGNATURE_NOT_VALID_FOR_ORDER)


def record_signature(order_id, transaction_id, *, actor):
    """Record the signature of a successful e-sign transaction (#8.1). Idempotent.

    Raises ``E14015`` for a transaction that is pending, another order's,
    another user's or from before a move back; and for one begun on an earlier
    business date, which is signed again so the date on the page is the day it
    was signed.
    """
    txn = ESignTransaction.objects.filter(pk=transaction_id).first()
    stale_date = False
    with transaction.atomic():
        order = common.lock_order(order_id)
        if order.is_signed:
            if (
                txn is not None
                and txn.signed_file_id
                and txn.signed_file_id == order.signed_file_id
            ):
                return order
            raise BusinessError(errors.ORDER_ALREADY_SIGNED)
        common.require_action(order, "sign")
        _check_transaction(txn, actor, order.pk, order.signing_file_id)
        if not order.number:
            raise BusinessError(errors.SIGNATURE_NOT_VALID_FOR_ORDER)
        if order.order_date != calendar.business_date():
            order.signing_file_id = ""
            common.save_order(order, actor, "signing expired: new business date")
            stale_date = True
        else:
            _finalise(order, txn.signed_file_id, SigningMethod.AADHAAR_ESIGN, actor)
    if stale_date:
        raise BusinessError(
            errors.SIGNATURE_NOT_VALID_FOR_ORDER,
            "This signing began on an earlier date. Sign the order again.",
        )
    return order


def record_signed_file(order_id, signed_file_id, method, *, actor):
    """Record a signature made outside ``apps.esign`` (a DSC module, per order or Roznama)."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "sign")
        _finalise(order, signed_file_id, method, actor)
        return order


def _finalise(order, signed_file_id, method, actor):
    order.status = OrderStatus.SIGNED
    order.signed_file_id = signed_file_id
    order.signing_method = method
    order.signed_by = actor
    order.signed_at = timezone.now()
    common.save_order(order, actor, "signed")
    ports.complete_task(order.pk, TaskKey.SIGN_ORDER)
    common.send_on_commit(signals.order_signed, order)
    notifications.notify_signed_on_commit(order)
    if order.data_complete:
        lifecycle.trigger(order, actor)


# -- Gujarat: the Roznama of a normal order -----------------------------------


def _roznama(order):
    roznama = OrderRoznama.objects.select_for_update().filter(order=order).first()
    if roznama is None or order.status != OrderStatus.TRIGGERED:
        raise BusinessError(errors.INVALID_ORDER_ACTION, "This order has no Roznama to sign.")
    return roznama


def start_roznama_signing(order_id, *, actor, method=SigningMethod.AADHAAR_ESIGN):
    """Prepare the Roznama PDF and start e-sign (#8.4): the diary entry, headed *Roznama*."""
    _require_method(method)
    with transaction.atomic():
        order = common.lock_order(order_id)
        roznama = _roznama(order)
        if roznama.status != RoznamaStatus.AWAITING_SIGNATURE:
            raise BusinessError(errors.DIARY_ENTRY_LOCKED, "This Roznama is already signed.")
        if not roznama.number:
            roznama.number = numbering.allot(order, NumberSeries.ROZNAMA)
        content = rendering.render_pdf(
            order,
            signing_user=actor,
            entry_text=diary.composed_entry(order),
            heading="Roznama",
            number=roznama.number,
            **_case_facts(order),
        )
        roznama.signing_file_id = _store(order, content, f"roznama-{order.pk}.pdf", actor)
        roznama.save(update_fields=["number", "signing_file_id", "updated_at"])
    return _initiate(order, actor, roznama.signing_file_id)


def record_roznama_signature(order_id, transaction_id, *, actor):
    """Record the Roznama's signature (#8.4). Triggers nothing and changes nothing on the order."""
    txn = ESignTransaction.objects.filter(pk=transaction_id).first()
    with transaction.atomic():
        order = common.lock_order(order_id)
        roznama = _roznama(order)
        if roznama.status == RoznamaStatus.SIGNED:
            if txn is not None and txn.signed_file_id == roznama.signed_file_id:
                return roznama
            raise BusinessError(errors.ORDER_ALREADY_SIGNED)
        _check_transaction(txn, actor, order.pk, roznama.signing_file_id)
        roznama.status = RoznamaStatus.SIGNED
        roznama.signed_file_id = txn.signed_file_id
        roznama.signing_method = SigningMethod.AADHAAR_ESIGN
        roznama.signed_by = actor
        roznama.signed_at = timezone.now()
        roznama.updated_by = actor
        roznama.save()
        ports.complete_task(order.pk, TaskKey.SIGN_ROZNAMA)
        common.send_on_commit(signals.roznama_signed, order)
        return roznama
