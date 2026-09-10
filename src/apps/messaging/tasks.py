"""Asynchronous message dispatch tasks."""

from django.conf import settings
from django.utils import timezone
from dramatiq import actor

from .models import MessageLog, MessageTemplate
from .senders import get_backend
from .services import MessageTemplateRenderer, resolve_template


@actor
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
        )
        log.rendered_subject = rendered.subject
        log.rendered_content = rendered.body
        log.save(update_fields=["rendered_subject", "rendered_content", "updated_at"])

        provider_message_id = get_backend(log.message_type).send(rendered)

        log.status = MessageLog.Status.SENT.value
        log.sent_at = timezone.now()
        log.error_message = ""
        if provider_message_id:
            log.provider_message_id = str(provider_message_id)
        log.save(
            update_fields=[
                "status",
                "sent_at",
                "error_message",
                "provider_message_id",
                "updated_at",
            ]
        )
    except Exception as exc:
        _record_failure(log, exc)


def _record_failure(log: MessageLog, exc: Exception) -> None:
    """Record a delivery failure and schedule a retry when allowed."""

    log.failed_at = timezone.now()
    log.error_message = str(exc)
    if log.can_retry():
        delay_ms = get_retry_delay_ms(log.attempt_count)
        log.save(update_fields=["failed_at", "error_message", "updated_at"])
        send_message.send_with_options(args=[str(log.id)], delay=delay_ms)
    else:
        log.status = MessageLog.Status.FAILED.value
        log.save(
            update_fields=["status", "failed_at", "error_message", "updated_at"]
        )


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
        max_retry=template.max_retry,
        status=MessageLog.Status.PENDING.value,
    )
    send_message.send(args=[str(log.id)])
    return log


def enqueue_email(message_key: str, recipient: dict, context: dict) -> MessageLog:
    """Enqueue an email message."""

    return _enqueue(
        MessageTemplate.MessageType.EMAIL.value,
        message_key,
        recipient,
        context,
    )


def enqueue_sms(message_key: str, recipient: dict, context: dict) -> MessageLog:
    """Enqueue an SMS message."""

    return _enqueue(
        MessageTemplate.MessageType.SMS.value,
        message_key,
        recipient,
        context,
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
        max_retry=template.max_retry,
        status=MessageLog.Status.PENDING.value,
    )
    log.status = MessageLog.Status.FAILED.value
    log.error_message = "Push notification delivery is not implemented yet."
    log.failed_at = timezone.now()
    log.save(
        update_fields=["status", "error_message", "failed_at", "updated_at"]
    )
    raise NotImplementedError("Push notification delivery is not implemented yet.")
