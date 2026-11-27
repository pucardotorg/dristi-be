"""Models, constraints, registry, checks, isolation, schedules (spec 0033 #3.2, #4, #16, #17.9)."""

import ast
import uuid
from io import StringIO
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.applications import conf
from apps.applications.checks import active_types_have_specs
from apps.applications.models import (
    Application,
    ApplicationTransition,
    ApplicationType,
)
from apps.applications.services import richtext
from apps.applications.types import registry
from apps.applications.types.base import ApplicationTypeSpec
from apps.applications.types.common import format_rupees

from .factories import set_config, submitted, type_row

pytestmark = pytest.mark.django_db

APPS_ROOT = Path(__file__).resolve().parents[2]


class TestConstraints:
    def base(self, world, **fields):
        values = {
            "case": world.case,
            "application_type": type_row("GENERIC"),
            "side": "COMPLAINANT",
            "created_by": world.a1,
            **fields,
        }
        return Application(**values)

    def save_raw(self, application):
        """Insert without ``clean()``: the database constraint alone must refuse it."""
        with pytest.raises(IntegrityError), transaction.atomic():
            Application.objects.bulk_create([application])

    def test_submitted_at_from_submission(self, world):
        self.save_raw(self.base(world, status="PENDING_REVIEW", signed_file_id="f"))

    def test_replaced_only_when_onboarded(self, world):
        self.save_raw(self.base(world, earlier_application_number="X"))

    def test_dismissed_before_onboarding(self, world):
        self.save_raw(
            self.base(
                world,
                status="DISMISSED",
                outcome="DISMISSED",
                signed_file_id="f",
                application_number="A",
                submitted_at=timezone.now(),
                onboarded_at=timezone.now(),
            )
        )

    def test_outcome_mirrors_the_status(self, world):
        self.save_raw(self.base(world, outcome="ACCEPTED"))

    def test_respond_by_needs_an_invitation(self, world):
        import datetime

        self.save_raw(self.base(world, respond_by=datetime.date(2026, 11, 19)))

    def test_signed_past_signature(self, world):
        self.save_raw(self.base(world, status="PENDING_PAYMENT"))

    def test_pending_decision_needs_onboarding(self, world):
        self.save_raw(
            self.base(
                world,
                status="PENDING_DECISION",
                signed_file_id="f",
                application_number="A",
                submitted_at=timezone.now(),
            )
        )

    def test_clean_objection_rules(self, world):
        target = submitted(world)
        objection = self.base(world, application_type=type_row("OBJECTION"), objection_to=target)
        with pytest.raises(ValidationError) as caught:
            objection.full_clean()
        assert "side" in caught.value.message_dict
        plain = self.base(world, objection_to=target)
        with pytest.raises(ValidationError) as caught:
            plain.full_clean()
        assert "objection_to" in caught.value.message_dict

    def test_clean_hearing_and_submitted_rules(self, world):
        app = self.base(world, application_type=type_row("POSTPONE_HEARING"))
        with pytest.raises(ValidationError) as caught:
            app.full_clean()
        assert "hearing_id" in caught.value.message_dict
        submitted_generic = self.base(world, status="SUBMITTED")
        with pytest.raises(ValidationError) as caught:
            submitted_generic.full_clean()
        assert "status" in caught.value.message_dict

    def test_str(self, world):
        app = submitted(world)
        assert str(app) == app.application_number
        assert "Generic" in str(type_row("GENERIC"))


class TestTransitionLog:
    def test_t125_append_only(self, world):
        app = submitted(world)
        row = app.transitions.first()
        row.summary = "changed"
        with pytest.raises(ValidationError):
            row.save()
        with pytest.raises(ValidationError):
            row.delete()
        with pytest.raises(ValidationError):
            ApplicationTransition.objects.filter(pk=row.pk).update(summary="x")
        with pytest.raises(ValidationError):
            ApplicationTransition.objects.filter(pk=row.pk).delete()
        assert str(row).startswith("SUBMIT")

    def test_delete_row_survives_the_draft(self, world):
        from .factories import client_for

        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {"application_type": "GENERIC"},
            format="json",
        )
        app_id = response.json()["id"]
        assert client_for(world.a1).delete(f"/api/v1/applications/{app_id}/").status_code == 204
        actions = list(
            ApplicationTransition.objects.filter(application_ref=app_id).values_list(
                "action", flat=True
            )
        )
        assert actions == ["CREATE", "DELETE"]


class TestTypes:
    def test_registry_refuses_a_second_spec(self):
        spec = registry.require("BAIL")
        with pytest.raises(ImproperlyConfigured):
            registry.register(spec)
        with pytest.raises(ImproperlyConfigured):
            registry.require("NOPE")
        assert "BAIL" in registry.codes()

    def test_type_code_must_be_registered_and_fixed(self):
        with pytest.raises(ValidationError):
            ApplicationType(code="NOPE", label="x", sequence=1).full_clean()
        with pytest.raises(ValidationError):
            ApplicationType(code="bad code", label="x", sequence=1).full_clean()
        row = type_row("GENERIC")
        row.code = "BAIL"
        with pytest.raises(ValidationError):
            row.save()

    def test_t127_system_check_for_a_type_with_no_spec(self, monkeypatch):
        assert active_types_have_specs(databases=["default"]) == []
        assert active_types_have_specs(databases=None) == []
        monkeypatch.setattr(registry, "get", lambda code: None if code == "GENERIC" else object())
        assert [e.id for e in active_types_have_specs(databases=["default"])] == [
            "applications.E001"
        ]

    def test_every_seeded_type_has_a_spec(self):
        assert set(ApplicationType.objects.values_list("code", flat=True)) == set(registry.codes())
        assert ApplicationType.objects.get(code="POA_CHANGE").is_active is False

    def test_default_hooks(self, world):
        spec = ApplicationTypeSpec()
        app = submitted(world)
        assert spec.render_entries(app) == []
        assert spec.on_accept(app, order_id=None, values={}) == {}
        assert spec.on_reject(app, order_id=None) is None
        assert spec.decision_hint(app) is None
        assert spec.document_label("x") == ""


class TestHelpers:
    def test_rich_text(self):
        assert richtext.sanitise("") == ""
        assert richtext.has_text("<p>&nbsp;</p>") is False
        assert richtext.to_text("<ul><li>a</li><li>b</li></ul>") == "• a\n• b"

    def test_rupees(self):
        assert format_rupees("50000") == "Rs. 50,000"
        assert format_rupees("1234567.5") == "Rs. 12,34,567.50"
        assert format_rupees("bad") == ""

    def test_conf_reads(self):
        set_config("applications", "edit_litigant_details", "not json")
        assert conf.edit_litigant_details()["editable"] == "OWN_LITIGANTS"
        set_config("applications", "fee.bail", "abc")
        assert str(conf.fee("", "BAIL")) == "0"
        set_config("applications", "non_working_weekdays", "SAT, SUN, XYZ")
        assert conf.non_working_weekdays("") == frozenset({5, 6})
        set_config("applications", "reschedule_reasons", "{}")
        assert conf.reschedule_reasons() == conf.DEFAULT_RESCHEDULE_REASONS
        set_config("applications", "suggested_by_stage", "[]")
        assert conf.suggested_by_stage() == {}
        set_config("applications", "edit_litigant_details", "[]")
        assert conf.edit_litigant_details() == conf.DEFAULT_EDIT_LITIGANT


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize(
    "upstream", ["cases", "hearings", "payments", "esign", "pdf", "files", "organizations"]
)
def test_t123_upstream_modules_do_not_import_applications(upstream):
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: {module}"
        for path in sorted((APPS_ROOT / upstream).rglob("*.py"))
        for module in imported_modules(path)
        if module.startswith("apps.applications")
    ]
    assert offenders == []


def test_applications_never_imports_an_addon():
    offenders = [
        str(path)
        for path in sorted((APPS_ROOT / "applications").rglob("*.py"))
        for module in imported_modules(path)
        if module.startswith("addon")
    ]
    assert offenders == []


def test_t126_scheduled_actors():
    from django.utils.module_loading import autodiscover_modules
    from dramatiq_crontab import scheduler

    autodiscover_modules("tasks")
    jobs = {job.name: str(job.trigger) for job in scheduler.get_jobs()}
    assert "expire_hearing_linked_applications" in jobs
    assert "close_objection_windows" in jobs


def test_t128_additional_attributes(world):
    from django.contrib.contenttypes.models import ContentType

    from apps.core.models import AdditionalAttribute

    app = submitted(world)
    app.additional_attributes = {"cis_reference": "R1"}
    with pytest.raises(ValidationError):
        app.full_clean()
    AdditionalAttribute.objects.create(
        content_type=ContentType.objects.get_for_model(Application),
        name="cis_reference",
        data_type="character",
    )
    app.full_clean()
    assert app.additional_attributes == {"cis_reference": "R1"}


def test_seed_list_includes_application_types():
    from django.core.management import call_command

    out = StringIO()
    call_command("seed", "--list", stdout=out)
    assert "applications.applicationtype" in out.getvalue().lower()


def test_uuid_helper():
    from apps.applications.types.base import is_uuid

    assert is_uuid(uuid.uuid4()) and not is_uuid("nope")
