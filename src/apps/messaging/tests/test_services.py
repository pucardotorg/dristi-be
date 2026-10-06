"""Tests for messaging services."""

from django.test import TestCase, override_settings

from apps.messaging.models import MessageTemplate
from apps.messaging.services import (
    MessageRenderError,
    MessageTemplateNotFound,
    MessageTemplateRenderer,
    RenderedMessage,
    resolve_template,
)


class TemplateResolutionTests(TestCase):
    """Template resolution tests."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="CASE_FILING_SUBMITTED",
            message_type=MessageTemplate.MessageType.EMAIL.value,
            subject="Case filed",
            content="Your case was filed.",
        )

    def test_resolve_active_template(self):
        resolved = resolve_template(
            "CASE_FILING_SUBMITTED",
            MessageTemplate.MessageType.EMAIL.value,
        )
        self.assertEqual(resolved.pk, self.template.pk)

    def test_inactive_template_not_resolved(self):
        self.template.is_active = False
        self.template.save()
        with self.assertRaises(MessageTemplateNotFound):
            resolve_template(
                "CASE_FILING_SUBMITTED",
                MessageTemplate.MessageType.EMAIL.value,
            )

    def test_missing_template_raises(self):
        with self.assertRaises(MessageTemplateNotFound):
            resolve_template("missing", MessageTemplate.MessageType.EMAIL.value)


class RendererTests(TestCase):
    """Template rendering tests."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="CASE_FILING_SUBMITTED",
            message_type=MessageTemplate.MessageType.EMAIL.value,
            subject="Case {{ case_number }} filed",
            content="Hello {{ name }}, your case {{ case_number }} was filed.",
            data_schema={
                "type": "object",
                "required": ["case_number", "name"],
                "properties": {
                    "case_number": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
        )
        self.renderer = MessageTemplateRenderer()

    def test_render_jinja2_subject_and_body(self):
        rendered = self.renderer.render(
            self.template,
            {"case_number": "CASE-1", "name": "Alice"},
            recipient={"email": "alice@example.com"},
        )
        self.assertIsInstance(rendered, RenderedMessage)
        self.assertEqual(rendered.subject, "Case CASE-1 filed")
        self.assertEqual(
            rendered.body,
            "Hello Alice, your case CASE-1 was filed.",
        )
        self.assertEqual(rendered.message_type, MessageTemplate.MessageType.EMAIL.value)
        self.assertEqual(rendered.category, self.template.category)
        self.assertEqual(rendered.recipient, {"email": "alice@example.com"})

    def test_render_autoescapes_html(self):
        rendered = self.renderer.render(
            self.template,
            {"case_number": "<script>", "name": "Alice"},
        )
        self.assertIn("&lt;script&gt;", rendered.subject)
        self.assertIn("&lt;script&gt;", rendered.body)

    def test_render_missing_variable_raises(self):
        with self.assertRaises(MessageRenderError):
            self.renderer.render(self.template, {"case_number": "CASE-1"})

    def test_render_validates_context_schema(self):
        with self.assertRaises(MessageRenderError):
            self.renderer.render(self.template, {"case_number": 123, "name": "Alice"})

    def test_render_without_schema_accepts_any_context(self):
        self.template.subject = "Static subject"
        self.template.content = "Static content"
        self.template.data_schema = {}
        self.template.save()
        rendered = self.renderer.render(self.template, {"anything": "goes"})
        self.assertEqual(rendered.subject, "Static subject")
        self.assertEqual(rendered.body, "Static content")

    def test_render_includes_category(self):
        self.template.category = MessageTemplate.Category.TRANSACTION.value
        self.template.save()
        rendered = self.renderer.render(
            self.template,
            {"case_number": "CASE-1", "name": "Alice"},
        )
        self.assertEqual(rendered.category, MessageTemplate.Category.TRANSACTION.value)

    def test_render_content_type_and_payload(self):
        rendered = self.renderer.render(
            self.template,
            {"case_number": "CASE-1", "name": "Alice"},
            content_type="html",
            from_email="noreply@example.com",
        )
        self.assertEqual(rendered.content_type, "html")
        self.assertEqual(rendered.payload["from_email"], "noreply@example.com")

    @override_settings(MESSAGING_TEMPLATE_ENGINE="unsupported")
    def test_unsupported_engine_raises(self):
        renderer = MessageTemplateRenderer()
        with self.assertRaises(MessageRenderError):
            renderer.render(
                self.template,
                {"case_number": "CASE-1", "name": "Alice"},
            )


class RenderedMessageMetadataTests(TestCase):
    """The renderer carries gateway-agnostic metadata to backends."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="RENDERER_METADATA_SMS",
            message_type=MessageTemplate.MessageType.SMS.value,
            subject="",
            content="Hello {{ name }}",
            category=MessageTemplate.Category.TRANSACTION.value,
            provider_template_id="dlt-9",
        )

    def test_metadata_is_populated(self):
        context = {"name": "Alice", "sms_content_type": "unicode"}
        rendered = MessageTemplateRenderer().render(
            self.template,
            context,
            recipient={"phone_number": "9876512345"},
            message_id="mid-1",
            correlation_id="cid-1",
            attempt=2,
        )
        self.assertEqual(rendered.provider_template_id, "dlt-9")
        self.assertEqual(rendered.context, context)
        self.assertEqual(rendered.message_id, "mid-1")
        self.assertEqual(rendered.correlation_id, "cid-1")
        self.assertEqual(rendered.attempt, 2)
        self.assertEqual(rendered.category, MessageTemplate.Category.TRANSACTION.value)

    def test_metadata_defaults_are_empty(self):
        rendered = MessageTemplateRenderer().render(self.template, {"name": "Alice"})
        self.assertEqual(rendered.message_id, "")
        self.assertEqual(rendered.correlation_id, "")
        self.assertEqual(rendered.attempt, 0)
