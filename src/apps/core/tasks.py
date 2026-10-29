"""Example Dramatiq background tasks."""

import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.utils import timezone
from django_dramatiq.models import DATABASE_LABEL, Task
from dramatiq import actor
from dramatiq_crontab import cron

logger = logging.getLogger(__name__)

# django_dramatiq writes one Task row per message; keep a week of them so a
# failure can still be investigated after a weekend (spec 0026 #7.1).
TASK_HISTORY_MAX_AGE = timedelta(days=7)


@actor
def send_welcome_email(email: str) -> None:
    """Send a welcome email to a new user."""
    send_mail(
        subject="Welcome to Dristi",
        message="Thanks for signing up!",
        from_email=None,
        recipient_list=[email],
        fail_silently=True,
    )


@actor
def process_long_running_job(job_id: str) -> str:
    """Placeholder for a CPU / IO intensive background job."""
    return f"job-{job_id}-completed"


@cron("0 21 * * *")  # daily, 02:30 IST
@actor(max_retries=0)
def prune_task_history() -> int:
    """Delete ``django_dramatiq`` task rows older than ``TASK_HISTORY_MAX_AGE``."""
    cutoff = timezone.now() - TASK_HISTORY_MAX_AGE
    deleted, _ = Task.tasks.using(DATABASE_LABEL).filter(created_at__lte=cutoff).delete()
    logger.info("event=TASK_HISTORY_PRUNED count=%s", deleted)
    return deleted
