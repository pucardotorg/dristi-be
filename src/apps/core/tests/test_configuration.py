"""Tests for the configuration store model, services, admin, and caching."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory

from apps.core import services
from apps.core.admin import ConfigurationAdmin
from apps.core.models import Configuration
from apps.core.services import (
    ConfigurationError,
    ConfigurationNotFound,
    ConfigurationService,
    ConfigurationValueError,
)

User = get_user_model()


def make(config_set="pdf", config_key="max_records_per_pdf", config_value="100", **kwargs):
    return Configuration.objects.create(
        config_set=config_set, config_key=config_key, config_value=config_value, **kwargs
    )


@pytest.mark.django_db
class TestConfigurationModel:
    """Normalization, format validation, and uniqueness."""

    def test_set_and_key_are_trimmed_and_lowercased(self):
        entry = make(config_set="  PDF ", config_key=" Max_Records_Per_PDF")
        entry.refresh_from_db()
        assert entry.config_set == "pdf"
        assert entry.config_key == "max_records_per_pdf"

    def test_duplicate_set_key_rejected(self):
        make()
        with pytest.raises(ValidationError):
            make(config_value="200")

    def test_case_normalized_collision_rejected(self):
        make(config_set="pdf")
        with pytest.raises(ValidationError):
            make(config_set="PDF")

    def test_database_constraint_enforced_without_model_validation(self):
        make()
        duplicate = Configuration(
            config_set="pdf", config_key="max_records_per_pdf", config_value="1"
        )
        with pytest.raises(IntegrityError):
            Configuration.objects.bulk_create([duplicate])

    def test_inactive_row_still_holds_its_key(self):
        make(is_active=False)
        with pytest.raises(ValidationError):
            make()

    @pytest.mark.parametrize("name", ["gateway.cdac.timeout", "sms", "page_size_2"])
    def test_valid_names_accepted(self, name):
        make(config_set=name, config_key=name)

    @pytest.mark.parametrize("name", ["", "has space", "dash-ed", ".leading", "trailing.", "a..b"])
    def test_invalid_names_rejected(self, name):
        with pytest.raises(ValidationError) as exc:
            make(config_key=name)
        assert "config_key" in exc.value.message_dict

    def test_empty_value_allowed(self):
        assert make(config_value="").config_value == ""

    def test_str(self):
        assert str(make()) == "pdf.max_records_per_pdf"


@pytest.mark.django_db
class TestGet:
    """``get()`` and ``get_set()`` return only active configuration."""

    def test_returns_value(self):
        make()
        assert services.get("pdf", "max_records_per_pdf") == "100"

    def test_lookup_is_normalized(self):
        make()
        assert services.get(" PDF", "Max_Records_Per_PDF ") == "100"

    def test_missing_key_raises(self):
        with pytest.raises(ConfigurationNotFound):
            services.get("pdf", "missing")

    def test_missing_key_returns_default(self):
        assert services.get("pdf", "missing", default="50") == "50"

    def test_none_is_a_valid_default(self):
        assert services.get("pdf", "missing", default=None) is None

    def test_inactive_key_treated_as_missing(self):
        make(is_active=False)
        with pytest.raises(ConfigurationNotFound):
            services.get("pdf", "max_records_per_pdf")
        assert services.get("pdf", "max_records_per_pdf", default="7") == "7"

    def test_empty_value_is_returned_not_treated_as_missing(self):
        make(config_value="")
        assert services.get("pdf", "max_records_per_pdf", default="x") == ""

    def test_get_set_returns_active_rows(self):
        make(config_key="max_records_per_pdf", config_value="100")
        make(config_key="default_template", config_value="court_notice")
        make(config_key="old_flag", config_value="1", is_active=False)
        make(config_set="sms", config_key="sender_id", config_value="DRISTI")

        assert services.get_set("PDF") == {
            "default_template": "court_notice",
            "max_records_per_pdf": "100",
        }

    def test_get_set_unknown_set_is_empty(self):
        assert services.get_set("nothing") == {}

    def test_exceptions_share_a_base(self):
        assert issubclass(ConfigurationNotFound, ConfigurationError)
        assert issubclass(ConfigurationValueError, ConfigurationError)

    def test_service_namespace(self):
        make()
        assert ConfigurationService.get("pdf", "max_records_per_pdf") == "100"
        assert ConfigurationService.get_int("pdf", "max_records_per_pdf") == 100


@pytest.mark.django_db
class TestCoercion:
    """Typed helpers parse strings; malformed values never fall back to the default."""

    @pytest.mark.parametrize(("raw", "expected"), [("30", 30), (" 30 ", 30), ("-5", -5)])
    def test_get_int(self, raw, expected):
        make(config_value=raw)
        assert services.get_int("pdf", "max_records_per_pdf") == expected

    @pytest.mark.parametrize("raw", ["abc", "1.5", ""])
    def test_get_int_invalid(self, raw):
        make(config_value=raw)
        with pytest.raises(ConfigurationValueError):
            services.get_int("pdf", "max_records_per_pdf", default=10)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("Yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("OFF", False),
        ],
    )
    def test_get_bool(self, raw, expected):
        make(config_key="enabled", config_value=raw)
        assert services.get_bool("pdf", "enabled") is expected

    @pytest.mark.parametrize("raw", ["maybe", "2", "", "y"])
    def test_get_bool_invalid(self, raw):
        make(config_key="enabled", config_value=raw)
        with pytest.raises(ConfigurationValueError):
            services.get_bool("pdf", "enabled", default=False)

    def test_get_json(self):
        make(config_key="limits", config_value='{"a": [1, 2]}')
        assert services.get_json("pdf", "limits") == {"a": [1, 2]}

    def test_get_json_invalid(self):
        make(config_key="limits", config_value="{not json")
        with pytest.raises(ConfigurationValueError):
            services.get_json("pdf", "limits", default={})

    @pytest.mark.parametrize("helper", [services.get_int, services.get_bool, services.get_json])
    def test_missing_uses_default(self, helper):
        assert helper("pdf", "missing", default="fallback") == "fallback"

    @pytest.mark.parametrize("helper", [services.get_int, services.get_bool, services.get_json])
    def test_missing_without_default_raises(self, helper):
        with pytest.raises(ConfigurationNotFound):
            helper("pdf", "missing")


@pytest.mark.django_db
class TestCaching:
    """Writes must be visible on the next read despite cachalot."""

    def test_table_is_cachable_but_other_core_tables_are_not(self):
        from cachalot.settings import cachalot_settings

        allowed = cachalot_settings.CACHALOT_ONLY_CACHABLE_TABLES
        assert "core_configuration" in allowed
        assert "locations_location" in allowed
        assert "core_additionalattribute" not in allowed

    def test_update_is_visible_on_next_read(self):
        entry = make()
        assert services.get("pdf", "max_records_per_pdf") == "100"
        entry.config_value = "250"
        entry.save()
        assert services.get("pdf", "max_records_per_pdf") == "250"

    def test_deactivation_is_visible_on_next_read(self):
        entry = make()
        assert services.get("pdf", "max_records_per_pdf") == "100"
        entry.is_active = False
        entry.save()
        assert services.get("pdf", "max_records_per_pdf", default=None) is None


@pytest.mark.django_db
class TestConfigurationAdmin:
    """Admin stamps audit fields and accepts un-normalized input."""

    @pytest.fixture
    def staff_user(self):
        return User.objects.create_user(
            mobile_number="+919000000010",
            name="ops",
            email="ops@example.com",
            password="x",
            is_staff=True,
            is_superuser=True,
        )

    @pytest.fixture
    def request_(self, staff_user):
        request = RequestFactory().post("/admin/")
        request.user = staff_user
        return request

    @pytest.fixture
    def model_admin(self):
        return ConfigurationAdmin(Configuration, AdminSite())

    def test_save_model_stamps_audit_fields(self, model_admin, request_, staff_user):
        entry = Configuration(config_set="pdf", config_key="max_records_per_pdf", config_value="1")
        model_admin.save_model(request_, entry, form=None, change=False)
        entry.refresh_from_db()
        assert entry.created_by == staff_user
        assert entry.updated_by == staff_user

    def test_form_normalizes_and_detects_case_collision(self, model_admin, request_):
        make()
        form_class = model_admin.get_form(request_, obj=None)
        data = {"config_set": "PDF", "config_key": "Max_Records_Per_PDF", "config_value": "2"}
        form = form_class(data={**data, "is_active": "on"})
        assert not form.is_valid()

        form = form_class(data={**data, "config_key": "Default_Template", "is_active": "on"})
        assert form.is_valid(), form.errors
        assert form.instance.config_set == "pdf"
        assert form.instance.config_key == "default_template"
