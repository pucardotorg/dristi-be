"""Email senders and SMTP backend."""

from django.conf import settings
from django.core.mail import EmailMessage

from apps.messaging.services import MessageSendError, RenderedMessage

from .base import ConfiguredBackendSender


class EmailSender(ConfiguredBackendSender):
    """Sender facade for the email channel."""

    message_type = "email"


class SMTPEmailBackend(EmailSender):
    """Email backend using Django's email facilities."""

    def send(self, rendered_message: RenderedMessage):
        # Concrete backends validate directly; calling super().send() would
        # delegate back to this class and recurse.
        self._validate_message_type(rendered_message)
        email = rendered_message.recipient.get("email")
        if not email:
            raise MessageSendError("Email recipient must include an 'email' address")

        from_email = getattr(settings, "MESSAGING_EMAIL_DEFAULT_FROM", None)
        from_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)

        message = EmailMessage(
            subject=rendered_message.subject,
            body=rendered_message.body,
            from_email=from_email,
            to=[email],
        )
        if rendered_message.content_type == "html":
            message.content_subtype = "html"

        backend = getattr(settings, "MESSAGING_EMAIL_BACKEND", "django")
        if backend == "django":
            message.send()
        elif backend == "smtp":
            from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

            smtp_backend = SMTPBackend(
                host=getattr(settings, "MESSAGING_EMAIL_HOST", None),
                port=getattr(settings, "MESSAGING_EMAIL_PORT", 587),
                username=getattr(settings, "MESSAGING_EMAIL_HOST_USER", None),
                password=getattr(settings, "MESSAGING_EMAIL_HOST_PASSWORD", None),
                use_tls=getattr(settings, "MESSAGING_EMAIL_USE_TLS", True),
                use_ssl=getattr(settings, "MESSAGING_EMAIL_USE_SSL", False),
                timeout=getattr(settings, "MESSAGING_EMAIL_TIMEOUT", 30),
            )
            if not smtp_backend.send_messages([message]):
                raise MessageSendError("SMTP server did not accept the email")
        else:
            raise MessageSendError(f"Unknown email backend: {backend}")

        return None
