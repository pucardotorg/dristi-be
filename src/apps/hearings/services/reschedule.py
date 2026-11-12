"""Moving a hearing that has not been heard: single and bulk (spec 0023 #8).

A move changes the date (and optionally the purpose) of a scheduled,
passed-over or abandoned hearing in place, so its id stays valid for the
processes and applications that point at it. Court staff move hearings for
court-side reasons only; party and judicial reasons need an order, which
moves the hearing through ``listing.confirm``.
"""

import datetime
import logging
import uuid
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.api import errors as api_errors
from apps.api.errors import BusinessError

from .. import conf, errors, signals
from ..enums import (
    COURT_SIDE_REASONS,
    MOVABLE_STATUSES,
    BulkItemResult,
    BulkMode,
    BulkRescheduleStatus,
    CalendarEntryType,
    ChangeSource,
    HearingStatus,
    RescheduleReason,
    Side,
)
from ..models import (
    BulkRescheduleItem,
    BulkRescheduleJob,
    Hearing,
    HearingAttendance,
    HearingDateChange,
)
from . import calendar, notifications
from .common import (
    SoftWarning,
    display_date,
    join_words,
    lock_hearing,
    record_scheduled_on_commit,
    require_transition,
    require_unmodified_since,
    save_hearing,
    send_on_commit,
)

logger = logging.getLogger(__name__)

PARTY_SIDES = (Side.COMPLAINANT, Side.ACCUSED)


@dataclass(frozen=True)
class MoveResult:
    """A moved hearing and the soft warnings of its move."""

    hearing: Hearing
    warnings: list = field(default_factory=list)


def adjournment_warnings(case_id):
    """``ADJOURNMENT_LIMIT_REACHED`` per party side at the threshold (#11.3, §346 BNSS).

    Only the parties are warned about: the limit is on adjournments a party
    obtains, and court-side moves are not the parties' doing.
    """
    from ..selectors import adjournment_counts

    threshold = conf.adjournment_warning_threshold()
    counts = adjournment_counts(case_id)
    return [
        SoftWarning(
            code="ADJOURNMENT_LIMIT_REACHED",
            message=(
                f"The {side.label.lower()} has already had {counts[side]} adjournments "
                "(§346 BNSS). A further one needs reasons recorded in the order."
            ),
            detail={"side": side.value, "count": counts[side]},
        )
        for side in PARTY_SIDES
        if counts[side] >= threshold
    ]


def other_scheduled(hearing):
    """Return another scheduled hearing of the hearing's case, or None."""
    return (
        Hearing.objects.filter(case_id=hearing.case_id, status=HearingStatus.SCHEDULED)
        .exclude(pk=hearing.pk)
        .first()
    )


def move(
    hearing,
    *,
    to_date,
    to_purpose,
    reason_code,
    reason_text="",
    sought_by=Side.COURT,
    source,
    source_ref=None,
    actor=None,
    notify=True,
):
    """Move the locked ``hearing`` in place and log it (#8.2 steps 2-4).

    The caller holds the court lock and the hearing lock, and has checked the
    transition, the date and the purpose. Writes the ``HearingDateChange``
    first, then the hearing: ``status = SCHEDULED``, ``reschedule_count + 1``,
    a new serial number on the new date (kept when only the purpose changes),
    and the reason on the history row. A move to another date clears the
    sitting on the old one (``_reset_sitting``). ``original_date`` and ``id`` never
    change. Queues the case-stage call when the purpose changed, the
    ``hearing_rescheduled`` signal and, unless ``notify`` is false, the
    parties' notification.
    """
    from_date, from_purpose = hearing.hearing_date, hearing.purpose
    change = HearingDateChange(
        hearing=hearing,
        from_date=from_date,
        to_date=to_date,
        from_purpose=from_purpose,
        to_purpose=to_purpose,
        reason_code=reason_code,
        reason_text=reason_text,
        sought_by=sought_by,
        source=source,
        source_ref=source_ref,
    )
    if actor is not None and getattr(actor, "pk", None):
        change.created_by = change.updated_by = actor
    change.save()

    # A purpose-only move keeps its place on the day's board.
    if to_date != from_date:
        hearing.sequence = calendar.next_sequence(hearing.court_id, to_date)
        _reset_sitting(hearing)
    hearing.hearing_date = to_date
    hearing.purpose = to_purpose
    hearing.status = HearingStatus.SCHEDULED
    hearing.reschedule_count += 1
    save_hearing(hearing, actor, f"{source} {RescheduleReason(reason_code).label}")

    if to_purpose.pk != from_purpose.pk:
        record_scheduled_on_commit(hearing)
    send_on_commit(
        signals.hearing_rescheduled,
        hearing_id=hearing.pk,
        case_id=hearing.case_id,
        from_date=from_date,
        to_date=to_date,
    )
    if notify:
        notify_rescheduled(hearing, from_date, reason_code)
    return change


def _reset_sitting(hearing):
    """Forget the sitting on the date moved away from: the new date is heard afresh (#6.5).

    A hearing started, then passed over or abandoned, keeps its start, heard time
    and attendance on the history table; carried to the new date they would open
    its roll pre-filled with another day's marks and count it complete (``ATT-04``).
    Locked marks are the record of a triggered order and are kept.
    """
    hearing.started_at = None
    hearing.last_started_at = None
    hearing.heard_duration = datetime.timedelta(0)
    if hearing.attendance_locked_at is None:
        HearingAttendance.objects.filter(hearing=hearing).delete()


def notify_rescheduled(hearing, from_date, reason_code):
    """Queue ``HEARING_RESCHEDULED`` to the case's parties and advocates (#11.1)."""
    notifications.notify_on_commit(
        hearing.case_id,
        notifications.HEARING_RESCHEDULED,
        {
            **notifications.case_context(hearing.case_id),
            "old_date": from_date.isoformat(),
            "new_date": hearing.hearing_date.isoformat(),
            "purpose": hearing.purpose.label,
            "reason": RescheduleReason(reason_code).label,
        },
    )


def _resolve_purpose(hearing, purpose_code):
    """Return the move's purpose: the hearing's own when not changed, else an active one."""
    if not purpose_code or purpose_code == hearing.purpose.code:
        return hearing.purpose
    purpose, problem = calendar.purpose_problem(purpose_code)
    if problem:
        raise BusinessError(problem.error, field="purpose")
    return purpose


def reschedule(
    *,
    hearing_id,
    hearing_date,
    purpose_code=None,
    reason_code,
    reason_text="",
    actor=None,
    court_id=None,
    if_unmodified_since=None,
):
    """Move a hearing to another date for a court-side reason, without an order (#8.2).

    Refuses a party or judicial reason (``400 E10013``), the same date and
    purpose (``400 E10012``), an invalid date (``E10005``-``E10008``), a case
    that already has another scheduled hearing (``409 E10004``) and, in
    ``block`` mode, a full day (``409 E10009``). A full day in ``warn`` mode and
    a party at the adjournment threshold come back as warnings.

    ``court_id`` limits the lookup to one court (``Hearing.DoesNotExist``
    otherwise). Returns a ``MoveResult``.
    """
    if reason_code not in COURT_SIDE_REASONS:
        raise BusinessError(errors.REASON_NEEDS_ORDER, field="reason_code")
    lookup = Hearing.objects.filter(pk=hearing_id)
    if court_id is not None:
        lookup = lookup.filter(court_id=court_id)
    court = lookup.values_list("court_id", flat=True).get()
    with transaction.atomic():
        calendar.lock_court(court)
        hearing = lock_hearing(hearing_id, court)
        require_unmodified_since(hearing, if_unmodified_since)
        require_transition(hearing, "reschedule", calendar.business_date())
        purpose = _resolve_purpose(hearing, purpose_code)
        if hearing_date == hearing.hearing_date and purpose.pk == hearing.purpose_id:
            raise BusinessError(errors.NOTHING_TO_CHANGE, field="hearing_date")
        warnings = _check_target(hearing, hearing_date)
        move(
            hearing,
            to_date=hearing_date,
            to_purpose=purpose,
            reason_code=reason_code,
            reason_text=reason_text,
            sought_by=Side.COURT,
            source=ChangeSource.COURT_ADMIN,
            actor=actor,
        )
        warnings += adjournment_warnings(hearing.case_id)
    return MoveResult(hearing=hearing, warnings=warnings)


def _check_target(hearing, hearing_date):
    """Check the new date and the case's other listings; return capacity warnings.

    The date is checked even when only the purpose changes: an abandoned
    hearing keeps its past date, and must not be scheduled on it again.
    """
    problems = calendar.date_problems(hearing.court_id, hearing_date)
    if problems:
        raise BusinessError(problems[0].error, problems[0].message, field="hearing_date")
    if other := other_scheduled(hearing):
        raise BusinessError(
            errors.CASE_ALREADY_SCHEDULED,
            f"This case is already scheduled for {display_date(other.hearing_date)}; "
            "move or cancel that hearing first.",
        )
    if hearing_date == hearing.hearing_date:
        return []
    load, full = calendar.capacity_check(hearing.court_id, hearing_date)
    if not full:
        return []
    if conf.capacity_mode() == conf.CAPACITY_BLOCK:
        raise BusinessError(
            errors.COURT_DAY_FULL, calendar.full_day_warning(load).message, field="hearing_date"
        )
    return [calendar.full_day_warning(load)]


# Bulk (#8.3)


@dataclass(frozen=True)
class BulkPreview:
    """A stored preview: the job, one line per hearing, and each target day's load."""

    job: BulkRescheduleJob
    lines: list
    loads: list


def _plan_next_available(hearings, court_id, schedule_after, today):
    """Fill sitting days after ``schedule_after`` in order, up to each day's free capacity.

    Keeps the hearings' relative order: dates never go backwards. A hearing
    is never planned onto its own date. Returns ``{hearing_id: to_date}``.
    """
    start = max(schedule_after + datetime.timedelta(days=1), today)
    horizon = today + datetime.timedelta(days=conf.max_days_ahead())
    if start > horizon:
        raise BusinessError(
            errors.DATE_BEYOND_HORIZON,
            f"Choose a schedule-after date before {display_date(horizon)}.",
            field="schedule_after",
        )
    loads = calendar.day_loads(court_id, start, horizon)
    free = {date: load.free for date, load in loads.items() if load.sitting}
    plan = {}
    cursor = start
    for hearing in hearings:
        date = cursor
        while date <= horizon and (free.get(date, 0) <= 0 or date == hearing.hearing_date):
            date += datetime.timedelta(days=1)
        if date > horizon:
            raise BusinessError(
                errors.DATE_BEYOND_HORIZON,
                "There are not enough free places on sitting days up to "
                f"{display_date(horizon)} for all these hearings. Move fewer at once.",
                field="schedule_after",
            )
        free[date] -= 1
        plan[hearing.pk] = date
        cursor = date
    return plan


def preview_bulk(
    *,
    court_id,
    hearing_ids,
    mode,
    target_date=None,
    schedule_after=None,
    block_source_dates=False,
    reason_code,
    reason_text="",
    actor=None,
):
    """Plan a court-side move of many hearings and store it as a preview (#8.3).

    ``TO_DATE`` moves every hearing to ``target_date``; ``NEXT_AVAILABLE``
    fills sitting days after ``schedule_after`` up to their free capacity,
    keeping the hearings' order on the board. Nothing but the job and its
    items is written. Refuses an order-only reason (``E10013``), more than
    ``bulk_max_hearings`` (``E10024``), a hearing of another court or unknown
    (``E00105``), one that cannot be moved (``E10001``), an invalid target date,
    and in ``block`` mode a target date without room for them all (``E10009``).
    """
    if reason_code not in COURT_SIDE_REASONS:
        raise BusinessError(errors.REASON_NEEDS_ORDER, field="reason_code")
    _check_bulk_mode(mode, target_date, schedule_after)
    hearing_ids = list(dict.fromkeys(_as_uuid(pk) for pk in hearing_ids))
    if not hearing_ids:
        raise BusinessError(
            api_errors.INVALID, "Choose at least one hearing to move.", field="hearing_ids"
        )
    if len(hearing_ids) > conf.bulk_max_hearings():
        raise BusinessError(
            errors.BULK_TOO_LARGE,
            f"At most {conf.bulk_max_hearings()} hearings can be moved at once.",
            field="hearing_ids",
        )
    today = calendar.business_date()
    with transaction.atomic():
        calendar.lock_court(court_id)
        hearings = list(
            Hearing.objects.filter(pk__in=hearing_ids, court_id=court_id)
            .select_related("purpose")
            .order_by("hearing_date", "status_order", "sequence")
        )
        found = {hearing.pk for hearing in hearings}
        missing = [str(pk) for pk in hearing_ids if pk not in found]
        if missing:
            raise BusinessError(
                api_errors.NOT_FOUND,
                f"These hearings are not on this court's list: {', '.join(missing)}.",
                field="hearing_ids",
            )
        unmovable = [h for h in hearings if h.status not in MOVABLE_STATUSES]
        if unmovable:
            raise BusinessError(
                errors.INVALID_TRANSITION,
                "Only scheduled, passed-over or abandoned hearings can be moved. These cannot: "
                + ", ".join(f"{h.pk} ({h.get_status_display().lower()})" for h in unmovable)
                + ".",
                field="hearing_ids",
            )
        if mode == BulkMode.TO_DATE:
            problems = calendar.date_problems(court_id, target_date, today=today)
            if problems:
                raise BusinessError(problems[0].error, problems[0].message, field="target_date")
            same = [str(h.pk) for h in hearings if h.hearing_date == target_date]
            if same:
                raise BusinessError(
                    errors.NOTHING_TO_CHANGE,
                    f"These hearings are already on {display_date(target_date)}: "
                    f"{', '.join(same)}. Leave them out or choose another date.",
                    field="hearing_ids",
                )
            _check_bulk_capacity(court_id, target_date, len(hearings))
            plan = {hearing.pk: target_date for hearing in hearings}
        else:
            plan = _plan_next_available(hearings, court_id, schedule_after, today)

        job = BulkRescheduleJob(
            court_id=court_id,
            mode=mode,
            target_date=target_date if mode == BulkMode.TO_DATE else None,
            schedule_after=schedule_after if mode == BulkMode.NEXT_AVAILABLE else None,
            block_source_dates=block_source_dates,
            reason_code=reason_code,
            reason_text=reason_text,
            preview_expires_at=timezone.now()
            + datetime.timedelta(minutes=conf.bulk_preview_minutes()),
        )
        if actor is not None and getattr(actor, "pk", None):
            job.created_by = job.updated_by = actor
        job.save()
        BulkRescheduleItem.objects.bulk_create(
            [
                BulkRescheduleItem(
                    job=job,
                    hearing=hearing,
                    hearing_updated_at=hearing.updated_at,
                    from_date=hearing.hearing_date,
                    to_date=plan[hearing.pk],
                )
                for hearing in hearings
            ]
        )
        lines = [
            {"hearing_id": h.pk, "from_date": h.hearing_date, "to_date": plan[h.pk]}
            for h in hearings
        ]
        loads = _target_loads(court_id, plan)
    return BulkPreview(job=job, lines=lines, loads=loads)


def _check_bulk_capacity(court_id, target_date, adding):
    """In ``block`` mode, refuse a move to one date that would overfill it (``409 E10009``).

    In ``warn`` mode the preview's ``loads`` show the overflow instead.
    """
    if conf.capacity_mode() != conf.CAPACITY_BLOCK:
        return
    load = calendar.day_load(court_id, target_date)
    if load.listed + load.provisional + adding <= load.capacity:
        return
    raise BusinessError(
        errors.COURT_DAY_FULL,
        f"The court's list for {display_date(target_date)} has {load.free} free "
        f"{'place' if load.free == 1 else 'places'} ({load.listed} listed and "
        f"{load.provisional} held in draft orders, against a capacity of {load.capacity}); "
        f"{adding} hearings cannot be moved there. Move fewer, or choose another date.",
        field="target_date",
    )


def _as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return value


def _check_bulk_mode(mode, target_date, schedule_after):
    """A move to one date needs ``target_date``; to the next available days, ``schedule_after``."""
    if mode not in BulkMode.values:
        raise BusinessError(
            api_errors.INVALID,
            f"Choose {join_words(BulkMode.values)} as the bulk move mode.",
            field="mode",
        )
    if mode == BulkMode.TO_DATE and target_date is None:
        raise BusinessError(
            api_errors.INVALID, "Choose the date to move the hearings to.", field="target_date"
        )
    if mode == BulkMode.NEXT_AVAILABLE and schedule_after is None:
        raise BusinessError(
            api_errors.INVALID,
            "Choose the date after which to fill the next available days.",
            field="schedule_after",
        )


def _target_loads(court_id, plan):
    """Each target day's load before and after the planned moves."""
    adding = {}
    for date in plan.values():
        adding[date] = adding.get(date, 0) + 1
    loads = []
    for date in sorted(adding):
        load = calendar.day_load(court_id, date)
        loads.append(
            {
                "date": date,
                "capacity": load.capacity,
                "provisional": load.provisional,
                "listed_before": load.listed,
                "listed_after": load.listed + adding[date],
            }
        )
    return loads


def confirm_bulk(*, job_id, actor):
    """Confirm a preview and queue the move (#8.3); returns the job, now ``QUEUED``.

    Refuses an expired preview (``409 E10015``) and one already confirmed
    (``409 E10016``). The job runs after commit.
    """
    from .. import tasks

    with transaction.atomic():
        job = BulkRescheduleJob.objects.select_for_update().get(pk=job_id)
        if job.status not in (BulkRescheduleStatus.PREVIEWED, BulkRescheduleStatus.EXPIRED):
            raise BusinessError(errors.PREVIEW_ALREADY_CONFIRMED)
        now = timezone.now()
        if job.status == BulkRescheduleStatus.EXPIRED or now > job.preview_expires_at:
            raise BusinessError(errors.PREVIEW_EXPIRED)
        job.status = BulkRescheduleStatus.QUEUED
        job.confirmed_at = now
        job.confirmed_by = actor
        job.updated_by = actor
        job.save()
        transaction.on_commit(lambda: tasks.run_bulk_reschedule.send(str(job.pk)))
    return job


def _item_error_code(exc):
    error = getattr(exc, "error", None)
    if error is not None:
        return error.code
    return api_errors.INVALID.code


def _move_item(job, item, today):
    """Move one item in its own transaction; return its result and error code."""
    with transaction.atomic():
        calendar.lock_court(job.court_id)
        hearing = lock_hearing(item.hearing_id)
        started = hearing.status in (HearingStatus.IN_PROGRESS, HearingStatus.COMPLETED) or (
            hearing.started_at is not None and hearing.started_at > item.hearing_updated_at
        )
        if started:
            return BulkItemResult.SKIPPED_STARTED, "", None
        # Also covers a hearing cancelled or moved since the preview.
        if hearing.status not in MOVABLE_STATUSES or hearing.updated_at != item.hearing_updated_at:
            return BulkItemResult.SKIPPED_CHANGED, "", None
        problems = calendar.date_problems(job.court_id, item.to_date, today=today)
        if problems:
            return BulkItemResult.FAILED, problems[0].error.code, None
        if other_scheduled(hearing):
            return BulkItemResult.FAILED, errors.CASE_ALREADY_SCHEDULED.code, None
        # The preview planned within capacity; the day may have filled since.
        if conf.capacity_mode() == conf.CAPACITY_BLOCK:
            _load, full = calendar.capacity_check(job.court_id, item.to_date)
            if full:
                return BulkItemResult.FAILED, errors.COURT_DAY_FULL.code, None
        move(
            hearing,
            to_date=item.to_date,
            to_purpose=hearing.purpose,
            reason_code=job.reason_code,
            reason_text=job.reason_text,
            sought_by=Side.COURT,
            source=ChangeSource.BULK,
            source_ref=job.pk,
            actor=job.confirmed_by,
            notify=False,
        )
        return BulkItemResult.MOVED, "", hearing


def run_bulk(job_id):
    """Run a confirmed bulk move; idempotent (#8.3, ``tasks.run_bulk_reschedule``).

    Processes only items still ``PENDING``, each in its own transaction, so a
    redelivered message finishes the job instead of repeating it. A hearing
    started or changed after the preview is skipped; any other failure is
    recorded with its error code without stopping the job. Notifies once per
    case. Then blocks the source dates if asked, and ends ``COMPLETED`` or
    ``PARTIALLY_FAILED``.
    """
    with transaction.atomic():
        job = BulkRescheduleJob.objects.select_for_update().get(pk=job_id)
        if job.status not in (BulkRescheduleStatus.QUEUED, BulkRescheduleStatus.RUNNING):
            logger.info("event=BULK_RESCHEDULE_SKIPPED job=%s status=%s", job.pk, job.status)
            return job
        job.status = BulkRescheduleStatus.RUNNING
        job.save()

    today = calendar.business_date()
    notified = set()
    for item in job.items.filter(result=BulkItemResult.PENDING).order_by("to_date", "from_date"):
        try:
            result, error_code, hearing = _move_item(job, item, today)
        except (BusinessError, ValidationError) as exc:
            result, error_code, hearing = BulkItemResult.FAILED, _item_error_code(exc), None
        except Exception:
            # Anything unexpected fails this item only; the job carries on (#8.3).
            logger.exception(
                "event=BULK_RESCHEDULE_ITEM_ERROR job=%s item=%s hearing=%s",
                job.pk,
                item.pk,
                item.hearing_id,
            )
            result, error_code, hearing = BulkItemResult.FAILED, api_errors.SERVER_ERROR.code, None
        if result == BulkItemResult.FAILED:
            logger.warning(
                "event=BULK_RESCHEDULE_ITEM_FAILED job=%s item=%s hearing=%s error=%s",
                job.pk,
                item.pk,
                item.hearing_id,
                error_code,
            )
        item.result = result
        item.error_code = error_code
        item.save()
        if hearing is not None and hearing.case_id not in notified:
            notified.add(hearing.case_id)
            notify_rescheduled(hearing, item.from_date, job.reason_code)

    if job.block_source_dates:
        _block_source_dates(job, today)

    with transaction.atomic():
        job = BulkRescheduleJob.objects.select_for_update().get(pk=job_id)
        failed = job.items.filter(result=BulkItemResult.FAILED).exists()
        job.status = (
            BulkRescheduleStatus.PARTIALLY_FAILED if failed else BulkRescheduleStatus.COMPLETED
        )
        job.save()
    logger.info("event=BULK_RESCHEDULE_DONE job=%s status=%s", job.pk, job.status)
    return job


def _block_source_dates(job, today):
    """Mark the dates hearings moved away from as non-sitting (#8.3).

    Past dates and dates that already have an entry are left alone; a date
    still holding listings is reported and left sitting (``E10017``).
    """
    from ..models import CourtCalendarEntry

    entry_type = (
        CalendarEntryType.PRESIDING_OFFICER_LEAVE
        if job.reason_code == RescheduleReason.PRESIDING_OFFICER_ON_LEAVE
        else CalendarEntryType.NON_SITTING
    )
    dates = set(
        job.items.filter(result=BulkItemResult.MOVED, from_date__gte=today).values_list(
            "from_date", flat=True
        )
    )
    for date in sorted(dates):
        if CourtCalendarEntry.objects.filter(court_id=job.court_id, date=date).exists():
            continue
        try:
            calendar.create_entry(
                court_id=job.court_id,
                date=date,
                entry_type=entry_type,
                reason=(job.reason_text or RescheduleReason(job.reason_code).label)[:255],
                actor=job.confirmed_by,
            )
        except BusinessError as exc:
            logger.warning(
                "event=BULK_RESCHEDULE_DATE_NOT_BLOCKED job=%s date=%s error=%s",
                job.pk,
                date,
                exc.error.code,
            )


def expire_previews():
    """Mark previews past their expiry ``EXPIRED``; return how many (#11.4)."""
    expired = 0
    stale = BulkRescheduleJob.objects.filter(
        status=BulkRescheduleStatus.PREVIEWED, preview_expires_at__lt=timezone.now()
    )
    for job in stale:
        job.status = BulkRescheduleStatus.EXPIRED
        job.save()
        expired += 1
    if expired:
        logger.info("event=BULK_PREVIEWS_EXPIRED count=%s", expired)
    return expired
