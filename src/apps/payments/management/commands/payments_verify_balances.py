"""Recompute every balance aggregate and report drift (spec 0017 #15). Read-only."""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from apps.payments.enums import DemandItemStatus, PaymentStatus
from apps.payments.models import ZERO, Demand, DemandItem, Payment, PaymentDemandItem


class Command(BaseCommand):
    """``manage.py payments_verify_balances`` — exits non-zero when anything drifted."""

    help = "Check the payment balance invariants of spec 0017 #15 without changing anything."

    def handle(self, *args, **options):
        problems = []
        problems += self._check_payments()
        problems += self._check_items()
        problems += self._check_demands()
        problems += self._check_batches()

        for problem in problems:
            self.stdout.write(problem)
        if problems:
            raise CommandError(f"{len(problems)} balance problem(s) found.")
        self.stdout.write(self.style.SUCCESS("All payment balances are consistent."))

    def _check_payments(self) -> list[str]:
        problems = []
        sums = defaultdict(lambda: ZERO)
        for row in PaymentDemandItem.objects.select_related("demand_item", "payment"):
            sums[row.payment_id] += row.amount
            if row.amount != row.demand_item.amount:
                problems.append(
                    f"{row.payment.payment_number}: pays {row.amount} for item "
                    f"{row.demand_item_id}, whose amount is {row.demand_item.amount}"
                )
        for payment in Payment.objects.all():
            if sums[payment.pk] != payment.amount:
                problems.append(
                    f"{payment.payment_number}: amount {payment.amount} != items {sums[payment.pk]}"
                )
        return problems

    def _check_items(self) -> list[str]:
        problems = []
        credited = defaultdict(lambda: ZERO)
        for row in PaymentDemandItem.objects.filter(payment__status=PaymentStatus.SUCCESS):
            credited[row.demand_item_id] += row.amount
        for item in DemandItem.objects.all():
            label = f"item {item.pk}"
            if credited[item.pk] != item.paid_amount:
                problems.append(
                    f"{label}: paid {item.paid_amount} != successful payments {credited[item.pk]}"
                )
            expected_due = (
                ZERO
                if item.status == DemandItemStatus.CANCELLED
                else (item.amount - item.paid_amount)
            )
            if item.due_amount != expected_due:
                problems.append(f"{label}: due {item.due_amount} != {expected_due}")
        return problems

    def _check_demands(self) -> list[str]:
        problems = []
        for demand in Demand.objects.prefetch_related("items"):
            live = [i for i in demand.items.all() if i.status != DemandItemStatus.CANCELLED]
            total = sum((i.amount for i in live), ZERO)
            paid = sum((i.paid_amount for i in live), ZERO)
            if (demand.total_amount, demand.paid_amount, demand.due_amount) != (
                total,
                paid,
                total - paid,
            ):
                problems.append(
                    f"{demand.demand_number}: total/paid/due "
                    f"{demand.total_amount}/{demand.paid_amount}/{demand.due_amount} "
                    f"!= {total}/{paid}/{total - paid}"
                )
        return problems

    def _check_batches(self) -> list[str]:
        problems = []
        batches = defaultdict(list)
        for payment in Payment.objects.exclude(batch_id=None):
            batches[payment.batch_id].append(payment)
        for batch_id, payments in batches.items():
            shapes = {(p.status, p.provider_payment_id, p.client_request_id) for p in payments}
            if len(shapes) > 1:
                problems.append(f"batch {batch_id}: payments disagree on status/provider id/key")
        return problems
