"""Scheduled jobs (spec 0026).

Pins the schedule inventory of spec 0026 #7.1, so a schedule that is added,
removed or changed fails here and shows up in review.
"""

from datetime import timedelta

import pytest
from apscheduler.triggers.cron import CronTrigger
from django.utils import timezone
from django.utils.module_loading import autodiscover_modules
from django_dramatiq.models import Task
from dramatiq import Message
from dramatiq_crontab import scheduler

from apps.core.tasks import TASK_HISTORY_MAX_AGE, prune_task_history

EXPECTED = {
    "expire_stale_transactions": "*/5 * * * *",
    "reconcile_signing_transactions": "*/5 * * * *",
    "cleanup_placeholders": "30 20 * * *",
    "prune_task_history": "0 21 * * *",
    "heartbeat": "* * * * *",
}


def test_schedule_inventory():
    """Every scheduled actor runs on the cadence the spec lists, and no other."""
    autodiscover_modules("tasks")  # what `manage.py crontab` does
    jobs = {job.name: str(job.trigger) for job in scheduler.get_jobs()}
    expected = {
        name: str(CronTrigger.from_crontab(expr, timezone=timezone.get_default_timezone()))
        for name, expr in EXPECTED.items()
    }
    assert jobs == expected


def _task(created_at):
    message = Message(queue_name="default", actor_name="noop", args=(), kwargs={}, options={})
    task = Task.tasks.create(
        id=message.message_id, message_data=message.encode(), status=Task.STATUS_DONE
    )
    Task.tasks.filter(pk=task.pk).update(created_at=created_at)
    return task


@pytest.mark.django_db
def test_prune_task_history_deletes_only_rows_past_retention():
    now = timezone.now()
    old = _task(now - TASK_HISTORY_MAX_AGE - timedelta(minutes=1))
    recent = _task(now - TASK_HISTORY_MAX_AGE + timedelta(hours=1))

    assert prune_task_history() == 1

    remaining = {str(pk) for pk in Task.tasks.values_list("pk", flat=True)}
    assert remaining == {str(recent.pk)}
    assert str(old.pk) not in remaining
