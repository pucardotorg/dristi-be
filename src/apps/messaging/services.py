"""Messaging domain services: rendering, resolution, and exceptions."""

from dataclasses import dataclass, field

from django.conf import settings

from .models import MessageTemplate


class MessageRenderError(Exception):
    """Raised when a template cannot be rendered."""


class MessageTemplateNotFound(Exception):  # noqa: N818
    """Raised when no active template matches a key and type."""


class MessageBackendNotConfigured(Exception):  # noqa: N818
    """Raised when a channel has no configured backend."""


class MessageSendError(Exception):
    """Raised when a backend fails to deliver a message.

    Backends may attach a machine-readable ``code`` and the raw
    ``gateway_status`` they observed; both are recorded in
    ``MessageLog.provider_metadata``.
    """

    def __init__(self, message: str = "", code: str = "", gateway_status: str = ""):
        super().__init__(message)
        self.code = code
        self.gateway_status = gateway_status


class MessagePermanentError(MessageSendError):
    """Raised when delivery failed for a reason retrying cannot fix."""


class RecipientFilteredError(Exception):  # noqa: N818
    """Raised when a recipient is suppressed by policy rather than failing."""

    def __init__(self, message: str = "", reason: str = ""):
        super().__init__(message)
        self.reason = reason


@dataclass
class RenderedMessage:
    """A fully rendered message ready for delivery."""

    message_type: str
    recipient: dict
    subject: str
    body: str
    message_key: str = ""
    content_type: str = "text/plain"
    category: str = ""
    payload: dict = field(default_factory=dict)
    provider_template_id: str = ""
    context: dict = field(default_factory=dict)
    message_id: str = ""
    correlation_id: str = ""
    attempt: int = 0


class MessageTemplateRenderer:
    """Render message templates with the configured template engine."""

    template_engine: str = "jinja2"

    def __init__(self, template_engine=None):
        self.template_engine = (
            template_engine or getattr(settings, "MESSAGING_TEMPLATE_ENGINE", self.template_engine)
        ).lower()
        self._jinja_env = None

    def render(
        self,
        template: MessageTemplate,
        context: dict,
        recipient: dict | None = None,
        message_key: str | None = None,
        message_id: str = "",
        correlation_id: str = "",
        attempt: int = 0,
        **payload,
    ) -> RenderedMessage:
        """Validate context and render subject and body."""

        try:
            self._validate_context(template, context)
            subject = self._render_string(template.subject, context)
            body = self._render_string(template.content, context)
        except MessageRenderError:
            raise
        except Exception as exc:
            raise MessageRenderError(f"Failed to render template: {exc}") from exc

        content_type = payload.pop("content_type", "text/plain")
        return RenderedMessage(
            message_type=template.message_type,
            recipient=recipient if recipient is not None else context.get("recipient", {}),
            subject=subject,
            body=body,
            message_key=message_key or template.message_key,
            content_type=content_type,
            category=template.category,
            payload=payload,
            provider_template_id=template.provider_template_id,
            context=context,
            message_id=message_id,
            correlation_id=correlation_id,
            attempt=attempt,
        )

    def _validate_context(self, template: MessageTemplate, context: dict):
        """Validate context against the template's JSON Schema."""

        schema = template.data_schema
        if not schema:
            return
        try:
            import jsonschema
        except ImportError as exc:
            raise MessageRenderError(
                "Rendering with data_schema requires the 'jsonschema' package"
            ) from exc
        try:
            jsonschema.validate(instance=context, schema=schema)
        except Exception as exc:
            raise MessageRenderError(f"Context validation failed: {exc}") from exc

    def _render_string(self, template_string: str, context: dict) -> str:
        """Render a single string with the configured engine."""

        if not template_string:
            return ""
        if self.template_engine == "jinja2":
            return self._get_jinja_env().from_string(template_string).render(**context)
        if self.template_engine in ("mustache", "pystache"):
            return self._render_mustache(template_string, context)
        raise MessageRenderError(f"Unsupported template engine: {self.template_engine}")

    def _get_jinja_env(self):
        """Return the cached Jinja2 sandbox environment."""

        if self._jinja_env is None:
            try:
                from jinja2 import StrictUndefined
                from jinja2.sandbox import SandboxedEnvironment
            except ImportError as exc:
                raise MessageRenderError("Jinja2 rendering requires the 'jinja2' package") from exc
            self._jinja_env = SandboxedEnvironment(
                autoescape=True,
                undefined=StrictUndefined,
            )
        return self._jinja_env

    def _render_mustache(self, template_string: str, context: dict) -> str:
        """Render a string with Mustache/pystache."""

        try:
            import pystache
        except ImportError as exc:
            raise MessageRenderError("Mustache rendering requires the 'pystache' package") from exc
        return pystache.render(template_string, context)


def resolve_template(message_key: str, message_type: str) -> MessageTemplate:
    """Resolve an active template by exact key and type match."""

    try:
        return MessageTemplate.objects.get(
            message_key=message_key,
            message_type=message_type,
            is_active=True,
        )
    except MessageTemplate.DoesNotExist as exc:
        raise MessageTemplateNotFound(
            f"No active template found for '{message_key}' ({message_type})"
        ) from exc
