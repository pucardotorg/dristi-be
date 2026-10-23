"""Collecting payments against demands (spec 0017 #6.2–#6.4, #7–#9).

Every path that moves money goes through ``PaymentService``:

* ``create_payment`` / ``create_batch`` validate under row locks, write the
  payment rows, then initiate with the default provider after commit;
* ``confirm_payment`` is the only place a balance is credited;
* ``apply_provider_status`` is the only consumer of a provider's verdict —
  callback, poll and cancel all go through it.

Lock order is always payments, then demands, then items, each by primary key,
so the services can never deadlock against each other.
"""

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.api import errors as api_errors
from apps.api.errors import BusinessError

from .. import errors
from ..enums import (
    FAILURE_CANCELLED,
    FAILURE_NOT_FOUND_AT_PROVIDER,
    FAILURE_PROVIDER_ERROR,
    FAILURE_PROVIDER_FAILED,
    OPEN_PAYMENT_STATUSES,
    DemandItemStatus,
    PaymentStatus,
)
from ..exceptions import PaymentNotConfirmable
from ..models import ZERO, Demand, DemandItem, Payment, PaymentDemandItem
from ..providers import registry
from ..providers.base import (
    ChargeLine,
    InitiationRequest,
    Payer,
    ProviderAction,
    ProviderError,
    ProviderNotConfigured,
    ProviderOutcome,
    ProviderPermanentError,
    ProviderStatus,
)
from . import balances
from .numbering import PAYMENT_PREFIX, next_number

logger = logging.getLogger(__name__)

PAYER_FIELDS = ("name", "email", "phone", "address", "city", "pincode")
UNAVAILABLE_MESSAGE = "The payment provider could not be reached."


class _KeyAlreadyUsed(Exception):  # noqa: N818
    """A concurrent request with the same key committed while this one waited for the lock."""


@dataclass(frozen=True)
class Selection:
    """The items of one demand a payment covers; ``field`` locates it in the request."""

    demand: Demand
    demand_item_ids: tuple
    field: str = "demand_item_ids"
    demand_field: str | None = None


@dataclass(frozen=True)
class Collection:
    """The outcome of a create-payment or create-batch call."""

    payments: list[Payment]
    created: bool
    action: ProviderAction | None

    @property
    def payment(self) -> Payment:
        """The payment of a single-demand collection."""

        return self.payments[0]

    @property
    def batch_id(self):
        """The shared batch id, or ``None`` for a single payment."""

        return self.payments[0].batch_id

    @property
    def amount(self) -> Decimal:
        """What the provider is asked to collect."""

        return sum((payment.amount for payment in self.payments), ZERO)


def payer_snapshot(payer: Mapping | None, actor) -> dict:
    """The payer details sent to the provider, defaulting from the caller's profile."""

    payer = dict(payer or {})
    defaults = {
        "name": getattr(actor, "name", "") or "",
        "email": getattr(actor, "email", "") or "",
        "phone": getattr(actor, "mobile_number", "") or "",
    }
    return {key: str(payer.get(key) or defaults.get(key, "") or "").strip() for key in PAYER_FIELDS}


def _as_uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _group(payment: Payment) -> list[Payment]:
    """The payment and every other payment of its batch, locked, by primary key."""

    queryset = Payment.objects.select_for_update()
    if payment.batch_id:
        queryset = queryset.filter(batch_id=payment.batch_id)
    else:
        queryset = queryset.filter(pk=payment.pk)
    return list(queryset.order_by("pk"))


def _enqueue_completion(payment_ids: list) -> None:
    """Tell the raising modules, once the credit is committed (spec 0017 #14)."""

    from ..tasks import notify_payment_completed

    for payment_id in payment_ids:
        try:
            notify_payment_completed.send(str(payment_id))
        except Exception:  # noqa: BLE001 - a broker outage must not undo a credit
            logger.exception("Could not enqueue completion of payment %s", payment_id)


class PaymentService:
    """Create, initiate, confirm, fail and cancel payments."""

    # -- creation -----------------------------------------------------------
    @classmethod
    def create_payment(
        cls,
        *,
        demand: Demand,
        demand_item_ids: Iterable,
        client_request_id: str,
        payer: Mapping | None = None,
        provider_options: Mapping | None = None,
        payment_mode: str = "",
        actor=None,
    ) -> Collection:
        """Pay the selected items of one demand (one item, a subset or all)."""

        selection = Selection(demand=demand, demand_item_ids=tuple(demand_item_ids))
        return cls._collect(
            [selection],
            batch=False,
            client_request_id=client_request_id,
            payer=payer,
            provider_options=provider_options,
            payment_mode=payment_mode,
            actor=actor,
        )

    @classmethod
    def create_batch(
        cls,
        *,
        selections: Iterable[Mapping],
        client_request_id: str,
        payer: Mapping | None = None,
        provider_options: Mapping | None = None,
        payment_mode: str = "",
        actor=None,
    ) -> Collection:
        """Pay across demands in one provider transaction; all or nothing.

        ``selections`` is ``[{"demand": Demand, "demand_item_ids": [...]}, ...]``.
        Each demand gets its own payment; they share a ``batch_id``.
        """

        from .. import conf

        selections = list(selections)
        if not selections:
            raise BusinessError(api_errors.EMPTY, field="selections")
        if len(selections) > conf.batch_max_demands():
            raise BusinessError(errors.BATCH_TOO_LARGE, field="selections")
        seen = set()
        parsed = []
        for index, selection in enumerate(selections):
            demand = selection["demand"]
            if demand.pk in seen:
                raise BusinessError(
                    errors.DEMAND_REPEATED_IN_BATCH, field=f"selections[{index}].demand_id"
                )
            seen.add(demand.pk)
            parsed.append(
                Selection(
                    demand=demand,
                    demand_item_ids=tuple(selection["demand_item_ids"]),
                    field=f"selections[{index}].demand_item_ids",
                    demand_field=f"selections[{index}].demand_id",
                )
            )
        return cls._collect(
            parsed,
            batch=True,
            client_request_id=client_request_id,
            payer=payer,
            provider_options=provider_options,
            payment_mode=payment_mode,
            actor=actor,
        )

    @classmethod
    def _collect(
        cls, selections, *, batch, client_request_id, payer, provider_options, payment_mode, actor
    ) -> Collection:
        if not client_request_id:
            raise BusinessError(api_errors.REQUIRED, field="client_request_id")

        existing = cls._find_existing(selections, client_request_id, batch=batch)
        if existing is not None:
            return cls._replay(existing)

        try:
            with transaction.atomic():
                payments = cls._create_rows(
                    selections,
                    batch=batch,
                    client_request_id=client_request_id,
                    payer=payer_snapshot(payer, actor),
                    provider_options={str(k): str(v) for k, v in (provider_options or {}).items()},
                    payment_mode=payment_mode or "",
                    actor=actor,
                )
        except (IntegrityError, _KeyAlreadyUsed):
            # A concurrent request with the same key won the race (spec 0017 #7).
            existing = cls._find_existing(selections, client_request_id, batch=batch)
            if existing is None:
                raise
            return cls._replay(existing)

        action = cls._initiate(payments)
        return Collection(payments=payments, created=True, action=action)

    @staticmethod
    def _find_existing(selections, client_request_id, *, batch) -> list[Payment] | None:
        """The payments a replayed ``client_request_id`` already created, if any."""

        demand_ids = [selection.demand.pk for selection in selections]
        found = list(
            Payment.objects.filter(demand_id__in=demand_ids, client_request_id=client_request_id)
        )
        if not found:
            return None

        batch_ids = {payment.batch_id for payment in found}
        if batch:
            if None in batch_ids or len(batch_ids) != 1:
                raise BusinessError(errors.CLIENT_REQUEST_ID_REUSED, field="client_request_id")
            payments = list(Payment.objects.filter(batch_id=batch_ids.pop()).order_by("pk"))
        else:
            if batch_ids != {None}:
                raise BusinessError(errors.CLIENT_REQUEST_ID_REUSED, field="client_request_id")
            payments = found

        requested = {
            selection.demand.pk: {_as_uuid(item_id) for item_id in selection.demand_item_ids}
            for selection in selections
        }
        actual = {payment.demand_id: set() for payment in payments}
        for row in PaymentDemandItem.objects.filter(payment__in=payments):
            actual[_payment_demand(payments, row.payment_id)].add(row.demand_item_id)
        if requested != actual:
            raise BusinessError(errors.CLIENT_REQUEST_ID_REUSED, field="client_request_id")
        return payments

    @classmethod
    def _replay(cls, payments: list[Payment]) -> Collection:
        """Return a replayed collection; a pending one gets its action rebuilt."""

        first = payments[0]
        action = None
        if first.status == PaymentStatus.PENDING and first.provider:
            action = cls._rebuild_action(payments)
        return Collection(payments=payments, created=False, action=action)

    @staticmethod
    def _create_rows(
        selections, *, batch, client_request_id, payer, provider_options, payment_mode, actor
    ) -> list[Payment]:
        demand_ids = sorted(selection.demand.pk for selection in selections)
        demands = {
            demand.pk: demand
            for demand in Demand.objects.select_for_update()
            .filter(pk__in=demand_ids)
            .order_by("pk")
        }
        wanted = {
            parsed
            for selection in selections
            for parsed in map(_as_uuid, selection.demand_item_ids)
            if parsed is not None
        }
        # Re-check the key under the lock: a retry that waited behind the request
        # that created the payment must replay it, not trip over its in-flight items.
        if Payment.objects.filter(
            demand_id__in=demand_ids, client_request_id=client_request_id
        ).exists():
            raise _KeyAlreadyUsed
        items = {
            item.pk: item
            for item in DemandItem.objects.select_for_update().filter(pk__in=wanted).order_by("pk")
        }
        in_flight = set(
            PaymentDemandItem.objects.filter(
                demand_item_id__in=wanted, payment__status__in=OPEN_PAYMENT_STATUSES
            ).values_list("demand_item_id", flat=True)
        )

        if len({demand.currency for demand in demands.values()}) > 1:
            raise BusinessError(errors.CURRENCY_MISMATCH)

        chosen: list[tuple[Demand, list[DemandItem]]] = []
        for selection in selections:
            demand = demands[selection.demand.pk]
            if not selection.demand_item_ids:
                raise BusinessError(api_errors.EMPTY, field=selection.field)
            if not demand.is_payable:
                raise BusinessError(errors.DEMAND_NOT_PAYABLE, field=selection.demand_field)

            seen = set()
            picked = []
            for index, raw in enumerate(selection.demand_item_ids):
                field = f"{selection.field}[{index}]"
                item_id = _as_uuid(raw)
                if item_id is not None and item_id in seen:
                    raise BusinessError(errors.DUPLICATE_DEMAND_ITEM, field=field)
                seen.add(item_id)
                item = items.get(item_id)
                if item is None or item.demand_id != demand.pk:
                    raise BusinessError(errors.ITEM_NOT_IN_DEMAND, field=field)
                if item.status != DemandItemStatus.UNPAID:
                    raise BusinessError(errors.ITEM_NOT_PAYABLE, field=field)
                if item.pk in in_flight:
                    raise BusinessError(errors.PAYMENT_IN_FLIGHT, field=field)
                picked.append(item)
            chosen.append((demand, picked))

        batch_id = uuid.uuid4() if batch else None
        now = timezone.now()
        metadata = {"provider_options": provider_options} if provider_options else {}
        payments = []
        for demand, picked in chosen:
            payment = Payment.objects.create(
                payment_number=next_number(PAYMENT_PREFIX),
                demand=demand,
                batch_id=batch_id,
                amount=sum((item.amount for item in picked), ZERO),
                currency=demand.currency,
                status=PaymentStatus.INITIATED,
                payment_mode=payment_mode,
                client_request_id=client_request_id,
                payer=payer,
                initiated_at=now,
                metadata=dict(metadata),
                created_by=actor,
                updated_by=actor,
            )
            for item in picked:
                PaymentDemandItem.objects.create(
                    payment=payment,
                    demand_item=item,
                    amount=item.amount,
                    created_by=actor,
                    updated_by=actor,
                )
            payments.append(payment)
        return payments

    # -- initiation (spec 0017 #9.4) ----------------------------------------
    @staticmethod
    def initiation_request(payments: list[Payment]) -> InitiationRequest:
        """Build the provider request from the stored snapshot; replayable."""

        payments = sorted(payments, key=lambda payment: payment.payment_number)
        first = payments[0]
        rows = (
            PaymentDemandItem.objects.filter(payment__in=payments)
            .select_related("payment", "payment__demand", "demand_item")
            .order_by("payment__payment_number", "demand_item__position", "demand_item_id")
        )
        lines = tuple(
            ChargeLine(
                payment_id=row.payment_id,
                demand_number=row.payment.demand.demand_number,
                demand_item_id=row.demand_item_id,
                charge_type=row.demand_item.charge_type,
                account_head=row.demand_item.account_head,
                description=row.demand_item.description,
                amount=row.amount,
            )
            for row in rows
        )
        payer = {key: str(first.payer.get(key) or "") for key in PAYER_FIELDS}
        return InitiationRequest(
            reference=first.batch_id or first.pk,
            payment_numbers=tuple(payment.payment_number for payment in payments),
            demand_numbers=tuple(payment.demand.demand_number for payment in payments),
            lines=lines,
            amount=sum((payment.amount for payment in payments), ZERO),
            currency=first.currency,
            payer=Payer(**payer),
            initiated_at=first.initiated_at,
            options=dict(first.metadata.get("provider_options") or {}),
        )

    @classmethod
    def _initiate(cls, payments: list[Payment]) -> ProviderAction | None:
        """Hand freshly created payments to the default provider."""

        try:
            provider = registry.get_default()
        except ProviderNotConfigured:
            logger.exception("The default payment provider is not configured.")
            cls.fail_payment(
                payments[0],
                failure_code=FAILURE_PROVIDER_ERROR,
                failure_message=UNAVAILABLE_MESSAGE,
            )
            raise BusinessError(errors.PROVIDER_UNAVAILABLE) from None
        if provider is None:
            # No provider: the payment stays INITIATED for an operator or an
            # internal service to confirm (spec 0017 #9.3).
            return None

        try:
            initiation = provider.initiate(cls.initiation_request(payments))
        except ProviderPermanentError as exc:
            cls.fail_payment(payments[0], failure_code=exc.code, failure_message=exc.message)
            if exc.field:
                raise BusinessError(
                    errors.PROVIDER_OPTION_INVALID, field=f"provider_options.{exc.field}"
                ) from exc
            raise BusinessError(errors.PROVIDER_REJECTED) from exc
        except Exception as exc:  # noqa: BLE001 - transient, or a provider bug
            if isinstance(exc, ProviderError):
                logger.warning("Payment provider %s unavailable: %s", provider.name, exc.code)
                code = exc.code
            else:
                logger.exception("Payment provider %s failed to initiate.", provider.name)
                code = FAILURE_PROVIDER_ERROR
            cls.fail_payment(payments[0], failure_code=code, failure_message=UNAVAILABLE_MESSAGE)
            raise BusinessError(errors.PROVIDER_UNAVAILABLE) from exc

        cls.mark_pending(
            payments,
            provider=provider.name,
            provider_payment_id=initiation.provider_payment_id,
            metadata=initiation.metadata,
        )
        for payment in payments:
            payment.refresh_from_db()
        return initiation.action

    @classmethod
    def _rebuild_action(cls, payments: list[Payment]) -> ProviderAction:
        """Re-run ``initiate`` on the stored snapshot of a pending payment (spec 0017 #9.4)."""

        first = payments[0]
        try:
            provider = registry.get(first.provider)
            initiation = provider.initiate(cls.initiation_request(payments))
        except ProviderPermanentError as exc:
            raise BusinessError(errors.PROVIDER_REJECTED) from exc
        except (ProviderError, ProviderNotConfigured) as exc:
            raise BusinessError(errors.PROVIDER_UNAVAILABLE) from exc

        if initiation.provider_payment_id != first.provider_payment_id:
            logger.error(
                "PROVIDER_REPLAY_MISMATCH: provider %s returned %s for %s on replay",
                first.provider,
                initiation.provider_payment_id,
                first.provider_payment_id,
            )
            raise BusinessError(errors.PROVIDER_REPLAY_MISMATCH)
        return initiation.action

    @staticmethod
    def mark_pending(payments, *, provider: str, provider_payment_id: str, metadata=None):
        """Record that ``payments`` were handed to ``provider``."""

        with transaction.atomic():
            locked = list(
                Payment.objects.select_for_update()
                .filter(pk__in=[payment.pk for payment in payments])
                .order_by("pk")
            )
            for payment in locked:
                if payment.status != PaymentStatus.INITIATED:
                    continue
                payment.status = PaymentStatus.PENDING
                payment.provider = provider
                payment.provider_payment_id = provider_payment_id
                payment.metadata = {**payment.metadata, "provider": dict(metadata or {})}
                payment.save(
                    update_fields=[
                        "status",
                        "provider",
                        "provider_payment_id",
                        "metadata",
                        "updated_at",
                    ]
                )
            return locked

    # -- outcomes (spec 0017 #6.4) ------------------------------------------
    @staticmethod
    def confirm_payment(
        payment: Payment, *, provider_reference: str = "", metadata=None, actor=None
    ) -> list[Payment]:
        """Credit the items of ``payment`` (and of its whole batch). Idempotent.

        A replay on an already successful payment returns it without a second
        credit; any other terminal state raises ``PaymentNotConfirmable``.
        """

        with transaction.atomic():
            payments = _group(payment)
            if all(p.status == PaymentStatus.SUCCESS for p in payments):
                return payments
            if any(not p.is_open for p in payments):
                raise PaymentNotConfirmable(f"Payment {payment.pk} cannot be confirmed.")

            demand_ids = sorted({p.demand_id for p in payments})
            demands = {
                demand.pk: demand
                for demand in Demand.objects.select_for_update()
                .filter(pk__in=demand_ids)
                .order_by("pk")
            }
            rows = list(
                PaymentDemandItem.objects.filter(payment__in=payments).order_by("demand_item_id")
            )
            items = {
                item.pk: item
                for item in DemandItem.objects.select_for_update()
                .filter(pk__in=[row.demand_item_id for row in rows])
                .order_by("pk")
            }

            now = timezone.now()
            for p in payments:
                p.status = PaymentStatus.SUCCESS
                p.completed_at = now
                p.provider_reference = provider_reference or p.provider_reference
                if metadata:
                    p.metadata = {
                        **p.metadata,
                        "provider": {**(p.metadata.get("provider") or {}), **metadata},
                    }
                p.updated_by = actor or p.updated_by
                p.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "provider_reference",
                        "metadata",
                        "updated_by",
                        "updated_at",
                    ]
                )
            for row in rows:
                balances.credit_item(items[row.demand_item_id], row.amount, actor=actor)
            for demand_id in demand_ids:
                balances.recompute_demand(demands[demand_id], actor=actor)

            ids = [p.pk for p in payments]
            transaction.on_commit(lambda: _enqueue_completion(ids))
            return payments

    @staticmethod
    def fail_payment(
        payment: Payment, *, failure_code: str, failure_message: str = "", actor=None
    ) -> list[Payment]:
        """Fail ``payment`` (and its batch); balances are untouched, items re-payable."""

        with transaction.atomic():
            payments = _group(payment)
            if any(p.status == PaymentStatus.SUCCESS for p in payments):
                raise PaymentNotConfirmable(f"Payment {payment.pk} already succeeded.")
            now = timezone.now()
            for p in payments:
                if not p.is_open:
                    continue
                p.status = PaymentStatus.FAILED
                p.failed_at = now
                p.failure_code = (failure_code or FAILURE_PROVIDER_FAILED)[:64]
                p.failure_message = failure_message
                p.updated_by = actor or p.updated_by
                p.save(
                    update_fields=[
                        "status",
                        "failed_at",
                        "failure_code",
                        "failure_message",
                        "updated_by",
                        "updated_at",
                    ]
                )
            return payments

    @staticmethod
    def cancel_payment(payment: Payment, *, reason: str = "", actor=None) -> list[Payment]:
        """Cancel an open payment (and its batch) locally; items become payable again."""

        with transaction.atomic():
            payments = _group(payment)
            if any(not p.is_open for p in payments):
                raise BusinessError(errors.PAYMENT_NOT_CANCELLABLE)
            now = timezone.now()
            for p in payments:
                p.status = PaymentStatus.CANCELLED
                p.cancelled_at = now
                p.failure_code = FAILURE_CANCELLED
                p.failure_message = reason
                p.updated_by = actor or p.updated_by
                p.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "failure_code",
                        "failure_message",
                        "updated_by",
                        "updated_at",
                    ]
                )
            return payments

    @classmethod
    def request_cancellation(cls, payment: Payment, *, actor, reason: str = "") -> list[Payment]:
        """The REST cancel flow: check with the provider before giving up (spec 0017 #9.8)."""

        if payment.created_by_id != getattr(actor, "pk", None):
            raise BusinessError(errors.NOT_PAYMENT_CREATOR)
        if not payment.is_open:
            raise BusinessError(errors.PAYMENT_NOT_CANCELLABLE)

        if payment.status == PaymentStatus.PENDING and payment.provider:
            try:
                provider = registry.get(payment.provider)
                status = provider.fetch_status(provider_payment_id=payment.provider_payment_id)
            except (ProviderError, ProviderNotConfigured) as exc:
                logger.warning("Could not verify payment %s before cancelling: %s", payment.pk, exc)
                raise BusinessError(errors.PROVIDER_UNAVAILABLE) from exc

            if status.outcome == ProviderOutcome.SUCCESS:
                cls.apply_provider_status(cls.provider_group(payment), status)
                payment.refresh_from_db()
                if payment.status == PaymentStatus.SUCCESS:
                    raise BusinessError(errors.PAYMENT_ALREADY_COMPLETED)
                raise BusinessError(errors.PAYMENT_OUTCOME_PENDING)
            if status.outcome == ProviderOutcome.PENDING:
                raise BusinessError(errors.PAYMENT_OUTCOME_PENDING)
            # NOT_FOUND or FAILED: the provider will not collect; cancel.

        return cls.cancel_payment(payment, reason=reason, actor=actor)

    # -- provider verdicts (spec 0017 #9.5) ---------------------------------
    @staticmethod
    def provider_group(payment: Payment) -> list[Payment]:
        """Every payment sharing ``payment``'s provider transaction."""

        if not (payment.provider and payment.provider_payment_id):
            return [payment]
        return list(
            Payment.objects.filter(
                provider=payment.provider, provider_payment_id=payment.provider_payment_id
            ).order_by("pk")
        )

    @classmethod
    def apply_provider_status(
        cls, payments: list[Payment], status: ProviderStatus
    ) -> list[Payment]:
        """Act on a provider's verdict for ``payments`` (one provider transaction)."""

        with transaction.atomic():
            locked = list(
                Payment.objects.select_for_update()
                .filter(pk__in=[payment.pk for payment in payments])
                .order_by("pk")
            )
            if not locked:
                return []
            outcome = status.outcome

            if all(p.is_open for p in locked):
                if outcome == ProviderOutcome.SUCCESS:
                    expected = sum((p.amount for p in locked), ZERO)
                    # Only a reported amount equal to the batch sum is credited; a
                    # success that reports no amount cannot be checked (spec 0017 #9.5).
                    if status.amount is None or Decimal(status.amount) != expected:
                        logger.error(
                            "PAYMENT_AMOUNT_MISMATCH: provider %s reported %s for %s, expected %s",
                            locked[0].provider,
                            status.amount,
                            status.provider_payment_id,
                            expected,
                        )
                        cls._flag(locked, "PAYMENT_AMOUNT_MISMATCH", status)
                        return locked
                    return cls.confirm_payment(
                        locked[0],
                        provider_reference=status.provider_reference,
                        metadata=status.metadata,
                    )
                if outcome == ProviderOutcome.FAILED:
                    return cls.fail_payment(
                        locked[0],
                        failure_code=status.failure_code or FAILURE_PROVIDER_FAILED,
                        failure_message=status.failure_message,
                    )
                if outcome == ProviderOutcome.NOT_FOUND and cls._not_found_is_final(locked):
                    return cls.fail_payment(
                        locked[0],
                        failure_code=FAILURE_NOT_FOUND_AT_PROVIDER,
                        failure_message="The payment provider has no record of this payment.",
                    )
                return locked

            if outcome == ProviderOutcome.SUCCESS and any(
                p.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED) for p in locked
            ):
                logger.error(
                    "PAYMENT_LATE_SUCCESS: provider %s reported success for terminal payment %s",
                    locked[0].provider,
                    status.provider_payment_id,
                )
                cls._flag(locked, "PAYMENT_LATE_SUCCESS", status)
            return locked

    @staticmethod
    def _not_found_is_final(payments: list[Payment]) -> bool:
        try:
            grace = registry.get(payments[0].provider).not_found_grace
        except ProviderNotConfigured:
            return False
        oldest = min(p.initiated_at for p in payments)
        return timezone.now() - oldest > grace

    @staticmethod
    def _flag(payments: list[Payment], reason: str, status: ProviderStatus | None = None):
        """Mark ``payments`` for an operator; never credits (spec 0017 #9.5)."""

        detail = {"reason": reason, "flagged_at": timezone.now().isoformat()}
        if status is not None:
            detail.update(
                outcome=str(status.outcome),
                amount=None if status.amount is None else str(status.amount),
                provider_reference=status.provider_reference,
            )
        for p in payments:
            p.needs_reconciliation = True
            p.metadata = {**p.metadata, "reconciliation": detail}
            p.save(update_fields=["needs_reconciliation", "metadata", "updated_at"])

    @classmethod
    def flag_for_reconciliation(cls, payments: list[Payment], reason: str) -> None:
        """Flag ``payments`` that need an operator, e.g. stuck past the provider horizon."""

        with transaction.atomic():
            locked = list(
                Payment.objects.select_for_update()
                .filter(pk__in=[p.pk for p in payments], needs_reconciliation=False)
                .order_by("pk")
            )
            if locked:
                cls._flag(locked, reason)

    @staticmethod
    def clear_reconciliation(payment: Payment, *, actor=None, note: str = "") -> Payment:
        """An operator's resolution of a flagged payment. Credits nothing."""

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if not payment.needs_reconciliation:
                return payment
            detail = dict(payment.metadata.get("reconciliation") or {})
            detail.update(
                resolved_at=timezone.now().isoformat(),
                resolved_by=str(getattr(actor, "pk", "") or ""),
                note=note,
            )
            payment.needs_reconciliation = False
            payment.metadata = {**payment.metadata, "reconciliation": detail}
            payment.updated_by = actor or payment.updated_by
            payment.save(
                update_fields=["needs_reconciliation", "metadata", "updated_by", "updated_at"]
            )
            return payment

    @classmethod
    def refresh_from_provider(cls, payment: Payment) -> list[Payment]:
        """Ask the payment's own provider for its status and apply it."""

        provider = registry.get(payment.provider)
        status = provider.fetch_status(provider_payment_id=payment.provider_payment_id)
        return cls.apply_provider_status(cls.provider_group(payment), status)


def _payment_demand(payments: list[Payment], payment_id) -> uuid.UUID:
    for payment in payments:
        if payment.pk == payment_id:
            return payment.demand_id
    raise KeyError(payment_id)
