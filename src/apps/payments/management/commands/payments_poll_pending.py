"""Run one status-poll pass (spec 0017 #9.7).

The project has no periodic scheduler yet, so the poller is driven from cron
(or any scheduler) with this command; ``--enqueue`` hands the pass to a
Dramatiq worker instead of running it inline.
"""

from django.core.management.base import BaseCommand

from apps.payments.services import polling
from apps.payments.tasks import poll_pending_payments


class Command(BaseCommand):
    """``manage.py payments_poll_pending [--enqueue]``."""

    help = "Poll providers for pending payments whose callback never arrived."

    def add_arguments(self, parser):
        parser.add_argument(
            "--enqueue", action="store_true", help="Send the pass to a worker instead."
        )

    def handle(self, *args, enqueue=False, **options):
        if enqueue:
            poll_pending_payments.send()
            self.stdout.write("Enqueued a status-poll pass.")
            return
        checked = polling.poll_pending_payments()
        self.stdout.write(f"Checked {checked} provider transaction(s).")
