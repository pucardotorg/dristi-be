"""How many payments a provider still holds (spec 0017 #9.8).

Before removing a provider, wait until this reports no open payments.
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.payments.enums import OPEN_PAYMENT_STATUSES
from apps.payments.models import Payment


class Command(BaseCommand):
    """``manage.py payments_provider_usage <provider>``."""

    help = "Count a provider's payments by status; open ones block its removal."

    def add_arguments(self, parser):
        parser.add_argument("provider", help="Provider name as stored in Payment.provider.")

    def handle(self, *args, provider, **options):
        rows = (
            Payment.objects.filter(provider=provider)
            .values("status")
            .annotate(count=Count("pk"))
            .order_by("status")
        )
        counts = {row["status"]: row["count"] for row in rows}
        for status_value, count in counts.items():
            self.stdout.write(f"{status_value}: {count}")

        open_count = sum(counts.get(s, 0) for s in OPEN_PAYMENT_STATUSES)
        if open_count:
            self.stdout.write(
                self.style.WARNING(f"{provider}: {open_count} open payment(s); keep it registered.")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"{provider}: no open payments; safe to remove."))
