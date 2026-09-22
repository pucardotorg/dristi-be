"""Asynchronous message dispatch tasks."""

import logging

from django.conf import settings
from django.utils import timezone
from dramatiq import actor

from .models import MessageLog, MessageTemplate
from .senders import get_backend
from .services import (
    MessagePermanentError,
    MessageTemplateRenderer,
    RecipientFilteredError,
    resolve_template,
)

logger = logging.getLogger(__name__)

_FAILURE_FIELDS = [
    "failed_at",
    "error_message",
    "failure_code",
    "gateway_status",
    "updated_at",
]


def _log_event(event: str, log: MessageLog, **extra) -> None:
    """Emit one structured line for a delivery lifecycle event."""

    fields = " ".join(f"{key}={value}" for key, value in extra.items())
    logger.info(
        "event=%s message_id=%s correlation_id=%s message_key=%s attempt=%s %s",
        event,
        log.id,
        log.correlation_id,
        log.message_key,
        log.attempt_count,
        fields,
    )


@actor(max_retries=0, time_limit=getattr(settings, "MESSAGING_TASK_TIME_LIMIT", 600000))
def send_message(log_id: str) -> None:
    """Deliver a queued message and update its MessageLog."""

    try:
        log = MessageLog.objects.get(id=log_id)
    except MessageLog.DoesNotExist:
        return None

    if log.status in (
        MessageLog.Status.SENT.value,
        MessageLog.Status.FAILED.value,
        MessageLog.Status.CANCELLED.value,
        MessageLog.Status.FILTERED.value,
    ):
        return None

    log.attempt_count += 1
    log.save(update_fields=["attempt_count", "updated_at"])

    try:
        template = resolve_template(log.message_key, log.message_type)
        rendered = MessageTemplateRenderer().render(
            template,
            log.context,
            recipient=log.recipient,
            message_key=log.message_key,
            message_id=str(log.id),
            correlation_id=log.correlation_id,
            attempt=log.attempt_count,
        )
        log.rendered_subject = rendered.subject
        log.rendered_content = rendered.body
        log.save(update_fields=["rendered_subject", "rendered_content", "updated_at"])

        sender = get_backend(log.message_type)
        provider_message_id = sender.send(rendered)

        log.status = MessageLog.Status.SENT.value
        log.sent_at = timezone.now()
        log.error_message = ""
        log.failure_code = ""
        log.gateway_status = ""
        log.provider = sender.get_provider_name()
        if provider_message_id:
            log.provider_message_id = str(provider_message_id)
        log.save(
            update_fields=[
                "status",
                "sent_at",
                "error_message",
                "failure_code",
                "gateway_status",
                "provider",
                "provider_message_id",
                "updated_at",
            ]
        )
        _log_event("SENT", log, status=log.status, provider=log.provider)
    except Exception as exc:
        _record_failure(log, exc)


def _record_failure(log: MessageLog, exc: Exception) -> None:
    """Classify a delivery outcome and schedule a retry when allowed."""

    if isinstance(exc, RecipientFilteredError):
        log.status = MessageLog.Status.FILTERED.value
        log.error_message = str(exc)
        log.failure_code = exc.reason
        log.save(update_fields=["status", "error_message", "failure_code", "updated_at"])
        _log_event("FILTERED", log, status=log.status, reason=exc.reason)
        return

    log.failed_at = timezone.now()
    log.error_message = str(exc)
    log.failure_code = getattr(exc, "code", "") or ""
    log.gateway_status = getattr(exc, "gateway_status", "") or ""

    if isinstance(exc, MessagePermanentError):
        log.status = MessageLog.Status.FAILED.value
        log.save(update_fields=_FAILURE_FIELDS + ["status"])
        _log_event("FAILED", log, status=log.status, failure_code=log.failure_code)
        return

    if log.can_retry():
        delay_ms = get_retry_delay_ms(log.attempt_count)
        log.save(update_fields=_FAILURE_FIELDS)
        send_message.send_with_options(args=(str(log.id),), delay=delay_ms)
        _log_event("RETRYING", log, status=log.status, delay_ms=delay_ms)
    else:
        log.status = MessageLog.Status.FAILED.value
        log.save(update_fields=_FAILURE_FIELDS + ["status"])
        _log_event("FAILED", log, status=log.status, failure_code=log.failure_code)


def get_retry_delay_ms(attempt_count: int) -> int:
    """Return exponential backoff delay in milliseconds."""

    base = getattr(settings, "MESSAGING_RETRY_DELAY_BASE", 60)
    maximum = getattr(settings, "MESSAGING_RETRY_DELAY_MAX", 3600)
    delay_seconds = base * (2 ** max(attempt_count - 1, 0))
    return int(min(delay_seconds, maximum) * 1000)


def _enqueue(
    message_type: str,
    message_key: str,
    recipient: dict,
    context: dict,
    correlation_id: str = "",
) -> MessageLog:
    """Create a log row and enqueue delivery."""

    if not isinstance(recipient, dict):
        raise ValueError("recipient must be a dictionary")
    if not isinstance(context, dict):
        raise ValueError("context must be a dictionary")

    template = resolve_template(message_key, message_type)
    log = MessageLog.objects.create(
        template=template,
        message_type=message_type,
        message_key=message_key,
        recipient=recipient,
        context=context,
        max_retries=template.max_retries,
        status=MessageLog.Status.PENDING.value,
        correlation_id=correlation_id,
    )
    if not log.correlation_id:
        log.correlation_id = str(log.id)
        log.save(update_fields=["correlation_id", "updated_at"])
    _log_event("ENQUEUED", log, status=log.status)
    send_message.send(str(log.id))
    return log


def enqueue_email(
    message_key: str,
    recipient: dict,
    context: dict,
    correlation_id: str = "",
) -> MessageLog:
    """Enqueue an email message."""

    return _enqueue(
        MessageTemplate.MessageType.EMAIL.value,
        message_key,
        recipient,
        context,
        correlation_id=correlation_id,
    )


def enqueue_sms(
    message_key: str,
    recipient: dict,
    context: dict,
    correlation_id: str = "",
) -> MessageLog:
    """Enqueue an SMS message."""

    return _enqueue(
        MessageTemplate.MessageType.SMS.value,
        message_key,
        recipient,
        context,
        correlation_id=correlation_id,
    )


def enqueue_push(message_key: str, recipient: dict, context: dict) -> MessageLog:
    """Record a push attempt as failed; push delivery is not implemented."""

    if not isinstance(recipient, dict):
        raise ValueError("recipient must be a dictionary")
    if not isinstance(context, dict):
        raise ValueError("context must be a dictionary")

    template = resolve_template(message_key, MessageTemplate.MessageType.PUSH.value)
    log = MessageLog.objects.create(
        template=template,
        message_type=MessageTemplate.MessageType.PUSH.value,
        message_key=message_key,
        recipient=recipient,
        context=context,
        max_retries=template.max_retries,
        status=MessageLog.Status.PENDING.value,
    )
    log.status = MessageLog.Status.FAILED.value
    log.error_message = "Push notification delivery is not implemented yet."
    log.failed_at = timezone.now()
    log.save(update_fields=["status", "error_message", "failed_at", "updated_at"])
    raise NotImplementedError("Push notification delivery is not implemented yet.")
