"""Tests for the public configuration store: model, services, API, admin, caching (spec 0034)."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.core import services
from apps.core.admin import PublicConfigurationAdmin
from apps.core.models import Configuration, PublicConfiguration
from apps.core.services import (
    ConfigurationNotFound,
    ConfigurationValueError,
    PublicConfigurationService,
)

User = get_user_model()

PUBLIC_FIELDS = {"config_set", "config_key", "value_type", "config_value"}
HIDDEN_FIELDS = {"id", "description", "is_active", "created_at", "updated_at"}
HIDDEN_FIELDS |= {"created_by", "updated_by"}


def make(
    config_set="ui_feature_flag",
    config_key="enable_dark_mode",
    config_value="false",
    value_type=PublicConfiguration.ValueType.BOOLEAN,
    **kwargs,
):
    return PublicConfiguration.objects.create(
        config_set=config_set,
        config_key=config_key,
        config_value=config_value,
        value_type=value_type,
        **kwargs,
    )


def make_string(config_set="pdf", config_key="default_template", config_value="court_notice"):
    return make(config_set, config_key, config_value, PublicConfiguration.ValueType.STRING)


def set_url(config_set):
    return reverse("public-configuration-by-set", kwargs={"config_set": config_set})


def key_url(config_set, config_key):
    return reverse(
        "public-configuration-by-key",
        kwargs={"config_set": config_set, "config_key": config_key},
    )


@pytest.fixture
def client():
    """An unauthenticated client: the endpoints are internet-facing."""
    return APIClient()


@pytest.mark.django_db
class TestPublicConfigurationModel:
    """Normalization, format validation, uniqueness, secrets and value types."""

    def test_set_and_key_are_trimmed_and_lowercased(self):
        entry = make(config_set="  UI_Feature_Flag ", config_key=" Enable_Dark_MODE")
        entry.refresh_from_db()
        assert entry.config_set == "ui_feature_flag"
        assert entry.config_key == "enable_dark_mode"

    def test_duplicate_set_key_rejected(self):
        make()
        with pytest.raises(ValidationError):
            make(config_value="true")

    def test_same_key_in_another_set_allowed(self):
        make(config_set="ui_feature_flag")
        make(config_set="registration")
        assert PublicConfiguration.objects.filter(config_key="enable_dark_mode").count() == 2

    def test_case_normalized_collision_rejected(self):
        make(config_set="pdf")
        with pytest.raises(ValidationError):
            make(config_set="PDF")

    def test_database_constraint_enforced_without_model_validation(self):
        make()
        duplicate = PublicConfiguration(
            config_set="ui_feature_flag", config_key="enable_dark_mode", config_value="true"
        )
        with pytest.raises(IntegrityError):
            PublicConfiguration.objects.bulk_create([duplicate])

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

    def test_value_type_defaults_to_string(self):
        entry = PublicConfiguration.objects.create(
            config_set="pdf", config_key="default_template", config_value="court_notice"
        )
        assert entry.value_type == PublicConfiguration.ValueType.STRING

    @pytest.mark.parametrize(
        ("value_type", "value"),
        [
            ("string", "court_notice"),
            ("string", ""),
            ("integer", "30"),
            ("integer", " -5 "),
            ("integer", "+7"),
            ("boolean", "true"),
            ("boolean", "True"),
            ("boolean", "OFF"),
            ("boolean", "1"),
            ("json", '{"pan": "Pan Card"}'),
            ("json", "[1, 2]"),
            ("json", '"text"'),
            ("json", "3"),
            ("json", "false"),
            ("json", "null"),
        ],
    )
    def test_matching_value_accepted(self, value_type, value):
        entry = make(config_value=value, value_type=value_type)
        entry.refresh_from_db()
        assert entry.config_value == value  # stored as entered, never rewritten

    @pytest.mark.parametrize(
        ("value_type", "value"),
        [
            ("integer", "abc"),
            ("integer", "1.5"),
            ("integer", ""),
            # coerce_integer accepts these, but a client's Number() does not
            # read them the same way.
            ("integer", "1_000"),
            ("integer", "1e3"),
            ("integer", "1.0"),
            ("integer", "\u0661\u0662"),  # Arabic-Indic digits
            ("boolean", "maybe"),
            ("boolean", "2"),
            ("boolean", ""),
            ("json", ""),
            ("json", "{not json"),
            ("json", "court_notice"),
            # Python's json accepts these; JSON.parse does not.
            ("json", "NaN"),
            ("json", "[Infinity]"),
            ("json", '{"x": -Infinity}'),
        ],
    )
    def test_mismatched_value_rejected(self, value_type, value):
        with pytest.raises(ValidationError) as exc:
            make(config_value=value, value_type=value_type)
        assert "value_type" in exc.value.message_dict
        assert not PublicConfiguration.objects.exists()

    def test_unknown_value_type_rejected(self):
        with pytest.raises(ValidationError) as exc:
            make(value_type="float", config_value="1.5")
        assert "value_type" in exc.value.message_dict

    @pytest.mark.parametrize(
        "name",
        [
            "gateway.password",
            "auth.token",
            "esign.private_key",
            "api_key",
            "secret",
            "credentials",
            "gateway_apikey",
            "sms.passwd",
            "access_token",
        ],
    )
    def test_secret_like_key_rejected(self, name):
        with pytest.raises(ValidationError) as exc:
            make_string(config_key=name)
        assert "config_key" in exc.value.message_dict

    def test_secret_like_set_rejected(self):
        with pytest.raises(ValidationError) as exc:
            make_string(config_set="gateway.credentials", config_key="endpoint")
        assert "config_set" in exc.value.message_dict

    def test_secret_like_name_detected_after_normalization(self):
        with pytest.raises(ValidationError):
            make_string(config_key="  Gateway.PASSWORD ")

    @pytest.mark.parametrize(
        "name", ["token_expiry_minutes", "password_min_length", "secretariat", "gateway.endpoint"]
    )
    def test_names_merely_containing_a_secret_word_accepted(self, name):
        make_string(config_key=name)

    def test_str(self):
        assert str(make()) == "ui_feature_flag.enable_dark_mode"


@pytest.mark.django_db
class TestOneStorePerKey:
    """A set/key pair lives in Configuration or PublicConfiguration, never both (section 1.3)."""

    def test_public_pair_rejected_when_private_exists(self):
        Configuration.objects.create(
            config_set="ui_feature_flag", config_key="enable_dark_mode", config_value="false"
        )
        with pytest.raises(ValidationError) as exc:
            make()
        assert "config_key" in exc.value.message_dict
        assert not PublicConfiguration.objects.exists()

    def test_private_pair_rejected_when_public_exists(self):
        make()
        with pytest.raises(ValidationError) as exc:
            Configuration.objects.create(
                config_set="ui_feature_flag", config_key="enable_dark_mode", config_value="x"
            )
        assert "config_key" in exc.value.message_dict
        assert not Configuration.objects.exists()

    def test_match_is_after_normalization(self):
        Configuration.objects.create(config_set="pdf", config_key="max", config_value="1")
        with pytest.raises(ValidationError):
            make_string(config_set=" PDF ", config_key="MAX")

    def test_inactive_row_still_claims_the_pair(self):
        Configuration.objects.create(
            config_set="pdf", config_key="max", config_value="1", is_active=False
        )
        with pytest.raises(ValidationError):
            make_string(config_set="pdf", config_key="max")

    def test_same_key_in_another_set_allowed(self):
        Configuration.objects.create(config_set="pdf", config_key="max", config_value="1")
        make_string(config_set="pdf_public", config_key="max")

    def test_existing_rows_can_still_be_updated(self):
        private = Configuration.objects.create(config_set="pdf", config_key="max", config_value="1")
        public = make()
        private.config_value = "2"
        private.save()
        public.config_value = "true"
        public.save()


@pytest.mark.django_db
class TestPublicServices:
    """The ``get_public*`` helpers read only active PublicConfiguration rows."""

    def test_get_public_returns_value(self):
        make()
        assert services.get_public("ui_feature_flag", "enable_dark_mode") == "false"

    def test_lookup_is_normalized(self):
        make()
        assert services.get_public(" UI_FEATURE_FLAG", "Enable_Dark_Mode ") == "false"

    def test_missing_key_raises(self):
        with pytest.raises(ConfigurationNotFound):
            services.get_public("ui_feature_flag", "missing")

    def test_missing_key_returns_default(self):
        assert services.get_public("ui_feature_flag", "missing", default="x") == "x"

    def test_none_is_a_valid_default(self):
        assert services.get_public("ui_feature_flag", "missing", default=None) is None

    def test_inactive_key_treated_as_missing(self):
        make(is_active=False)
        with pytest.raises(ConfigurationNotFound):
            services.get_public("ui_feature_flag", "enable_dark_mode")
        assert services.get_public("ui_feature_flag", "enable_dark_mode", default="7") == "7"

    def test_private_store_is_not_read(self):
        Configuration.objects.create(config_set="pdf", config_key="max", config_value="100")
        with pytest.raises(ConfigurationNotFound):
            services.get_public("pdf", "max")

    def test_get_public_set(self):
        make(config_key="enable_dark_mode", config_value="false")
        make(config_key="enable_bulk_case_select", config_value="true")
        make(config_key="old_flag", config_value="true", is_active=False)
        make(config_set="registration", config_key="show_welcome_message")

        assert services.get_public_set("UI_FEATURE_FLAG") == {
            "enable_bulk_case_select": "true",
            "enable_dark_mode": "false",
        }

    def test_get_public_set_unknown_set_is_empty(self):
        assert services.get_public_set("nothing") == {}

    def test_get_public_int(self):
        make(config_key="page_size", config_value=" 25 ", value_type="integer")
        assert services.get_public_int("ui_feature_flag", "page_size") == 25

    @pytest.mark.parametrize(
        ("raw", "expected"), [("true", True), ("Yes", True), ("ON", True), ("0", False)]
    )
    def test_get_public_bool(self, raw, expected):
        make(config_value=raw)
        assert services.get_public_bool("ui_feature_flag", "enable_dark_mode") is expected

    def test_get_public_json(self):
        make(config_key="options", config_value='{"pan": "Pan Card"}', value_type="json")
        assert services.get_public_json("ui_feature_flag", "options") == {"pan": "Pan Card"}

    @pytest.mark.parametrize(
        ("helper", "default"),
        [
            (services.get_public_int, 10),
            (services.get_public_bool, False),
            (services.get_public_json, {}),
        ],
    )
    def test_malformed_value_raises_without_falling_back(self, helper, default):
        # A string-typed entry may hold anything; the typed helpers still parse it.
        make_string(config_key="value", config_value="not-a-number-bool-or-json")
        with pytest.raises(ConfigurationValueError):
            helper("pdf", "value", default=default)

    @pytest.mark.parametrize(
        "helper", [services.get_public_int, services.get_public_bool, services.get_public_json]
    )
    def test_missing_uses_default_or_raises(self, helper):
        assert helper("pdf", "missing", default="fallback") == "fallback"
        with pytest.raises(ConfigurationNotFound):
            helper("pdf", "missing")

    def test_service_namespace(self):
        make()
        assert PublicConfigurationService.get_public_bool(
            "ui_feature_flag", "enable_dark_mode"
        ) is (False)


@pytest.mark.django_db
class TestSetListingAPI:
    """GET /api/v1/public-configuration/{config_set}/."""

    def test_url(self):
        assert set_url("ui_feature_flag") == "/api/v1/public-configuration/ui_feature_flag/"

    def test_public_paginated_with_meta(self, client):
        make(config_key="enable_dark_mode", config_value="false")
        make(config_key="enable_bulk_case_select", config_value="true")

        response = client.get(set_url("ui_feature_flag"))

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["next"] is None
        assert body["previous"] is None
        assert {"timestamp", "app_version", "spec_version"} <= set(body["meta"])
        assert body["results"] == [
            {
                "config_set": "ui_feature_flag",
                "config_key": "enable_bulk_case_select",
                "value_type": "boolean",
                "config_value": "true",
            },
            {
                "config_set": "ui_feature_flag",
                "config_key": "enable_dark_mode",
                "value_type": "boolean",
                "config_value": "false",
            },
        ]

    def test_only_active_rows_of_that_set(self, client):
        make(config_key="enable_dark_mode")
        make(config_key="old_flag", is_active=False)
        make(config_set="registration", config_key="show_welcome_message")

        body = client.get(set_url("ui_feature_flag")).json()

        assert [row["config_key"] for row in body["results"]] == ["enable_dark_mode"]

    def test_set_is_normalized(self, client):
        make()
        body = client.get(set_url("UI_FEATURE_FLAG")).json()
        assert body["count"] == 1

    def test_dotted_set(self, client):
        make_string(config_set="gateway.cdac", config_key="endpoint")
        body = client.get(set_url("gateway.cdac")).json()
        assert body["results"][0]["config_key"] == "endpoint"

    def test_paginates_with_project_page_size(self, client):
        for index in range(21):
            make(config_key=f"flag_{index:02d}")
        body = client.get(set_url("ui_feature_flag")).json()
        assert body["count"] == 21
        assert len(body["results"]) == 20
        assert body["next"]

    @pytest.mark.parametrize("config_set", ["unknown", "inactive_set"])
    def test_unknown_or_inactive_set_returns_empty_page(self, client, config_set):
        make(config_set="inactive_set", is_active=False)
        response = client.get(set_url(config_set))
        assert response.status_code == 200
        assert response.json()["count"] == 0
        assert response.json()["results"] == []

    def test_set_only_in_private_store_is_empty(self, client):
        Configuration.objects.create(config_set="pdf", config_key="max", config_value="100")
        assert client.get(set_url("pdf")).json()["count"] == 0

    def test_ordering_and_filter_params_are_ignored(self, client):
        make(config_key="b_flag")
        make(config_key="a_flag")
        make(config_key="c_flag", is_active=False)
        body = client.get(
            set_url("ui_feature_flag"),
            {"ordering": "-config_key", "is_active": "false", "config_set": "other"},
        ).json()
        assert [row["config_key"] for row in body["results"]] == ["a_flag", "b_flag"]

    def test_results_hide_admin_metadata(self, client):
        make(description="internal note")
        row = client.get(set_url("ui_feature_flag")).json()["results"][0]
        assert set(row) == PUBLIC_FIELDS
        assert not HIDDEN_FIELDS & set(row)


@pytest.mark.django_db
class TestDetailAPI:
    """GET /api/v1/public-configuration/{config_set}/{config_key}/."""

    def test_url(self):
        assert key_url("pdf", "default_template") == (
            "/api/v1/public-configuration/pdf/default_template/"
        )

    def test_returns_entry_with_meta(self, client):
        make(description="internal note")

        response = client.get(key_url("ui_feature_flag", "enable_dark_mode"))

        assert response.status_code == 200
        body = response.json()
        meta = body.pop("meta")
        assert {"timestamp", "app_version", "spec_version"} <= set(meta)
        assert body == {
            "config_set": "ui_feature_flag",
            "config_key": "enable_dark_mode",
            "value_type": "boolean",
            "config_value": "false",
        }
        assert not HIDDEN_FIELDS & set(body)

    def test_path_parameters_are_normalized(self, client):
        make()
        response = client.get(key_url("UI_FEATURE_FLAG", "Enable_Dark_Mode"))
        assert response.status_code == 200
        assert response.json()["config_key"] == "enable_dark_mode"

    def test_dotted_names(self, client):
        make_string(config_set="gateway.cdac", config_key="sms.sender_id", config_value="DRISTI")
        response = client.get(key_url("gateway.cdac", "sms.sender_id"))
        assert response.json()["config_value"] == "DRISTI"

    def test_json_value_is_returned_as_a_string(self, client):
        stored = '{"pan": "Pan Card", "epic_id": "Voter ID"}'
        make(
            config_set="efiling_cheque_fraud",
            config_key="identity_drop_down",
            config_value=stored,
            value_type="json",
        )
        body = client.get(key_url("efiling_cheque_fraud", "identity_drop_down")).json()
        assert body["value_type"] == "json"
        assert body["config_value"] == stored

    def test_key_from_another_set_is_not_returned(self, client):
        make(config_set="registration")
        response = client.get(key_url("ui_feature_flag", "enable_dark_mode"))
        assert response.status_code == 404

    @pytest.mark.parametrize("is_active", [None, False])
    def test_unknown_or_inactive_returns_404_error_body(self, client, is_active):
        if is_active is not None:
            make(is_active=is_active)
        response = client.get(key_url("ui_feature_flag", "enable_dark_mode"))
        assert response.status_code == 404
        body = response.json()
        assert body["errors"][0]["code"] == "E00105"
        assert "meta" in body

    def test_key_only_in_private_store_is_not_returned(self, client):
        Configuration.objects.create(
            config_set="ui_feature_flag", config_key="enable_dark_mode", config_value="secret"
        )
        assert client.get(key_url("ui_feature_flag", "enable_dark_mode")).status_code == 404

    def test_public_row_wins_over_similarly_named_private_row(self, client):
        make(config_value="true")
        # The models refuse this pair; bulk_create skips validation to prove the
        # view still never reads Configuration if such data exists.
        Configuration.objects.bulk_create(
            [
                Configuration(
                    config_set="ui_feature_flag",
                    config_key="enable_dark_mode",
                    config_value="private",
                )
            ]
        )
        body = client.get(key_url("ui_feature_flag", "enable_dark_mode")).json()
        assert body["config_value"] == "true"


@pytest.mark.django_db
class TestReadOnlyAndRouting:
    """Only the two GET routes exist."""

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    @pytest.mark.parametrize(
        "url", [set_url("ui_feature_flag"), key_url("ui_feature_flag", "enable_dark_mode")]
    )
    def test_write_methods_rejected(self, client, method, url):
        make()
        response = getattr(client, method)(url, {"config_value": "true"}, format="json")
        assert response.status_code == 405
        assert PublicConfiguration.objects.get().config_value == "false"

    @pytest.mark.parametrize(
        "url", [set_url("ui_feature_flag"), key_url("ui_feature_flag", "enable_dark_mode")]
    )
    def test_missing_trailing_slash_redirects(self, client, url):
        response = client.get(url.rstrip("/"))
        assert response.status_code == 301
        assert response["Location"].endswith(url)

    def test_no_global_list_route(self, client):
        assert client.get("/api/v1/public-configuration/").status_code == 404

    def test_schema_documents_only_the_two_routes(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = {
            path: ops for path, ops in schema["paths"].items() if "public-configuration" in path
        }

        assert set(paths) == {
            "/api/v1/public-configuration/{config_set}/",
            "/api/v1/public-configuration/{config_set}/{config_key}/",
        }
        for operations in paths.values():
            assert set(operations) - {"parameters"} == {"get"}
            assert operations["get"]["tags"] == ["core"]

        by_set = paths["/api/v1/public-configuration/{config_set}/"]["get"]
        list_schema = by_set["responses"]["200"]["content"]["application/json"]["schema"]
        assert "PaginatedPublicConfigurationList" in str(list_schema)


@pytest.mark.django_db
class TestCaching:
    """Writes must be visible on the next read despite cachalot."""

    def test_table_is_cachable_but_other_core_tables_are_not(self):
        from cachalot.settings import cachalot_settings

        allowed = cachalot_settings.CACHALOT_ONLY_CACHABLE_TABLES
        assert "core_publicconfiguration" in allowed
        assert "core_additionalattribute" not in allowed
        assert "core_historicaladditionalattribute" not in allowed
        assert "core" not in cachalot_settings.CACHALOT_ONLY_CACHABLE_APPS

    def test_update_is_visible_on_next_read(self, client):
        entry = make()
        assert services.get_public("ui_feature_flag", "enable_dark_mode") == "false"
        assert client.get(set_url("ui_feature_flag")).json()["count"] == 1
        entry.config_value = "true"
        entry.save()
        assert services.get_public("ui_feature_flag", "enable_dark_mode") == "true"
        url = key_url("ui_feature_flag", "enable_dark_mode")
        assert client.get(url).json()["config_value"] == "true"

    def test_deactivation_is_visible_on_next_read(self, client):
        entry = make()
        url = key_url("ui_feature_flag", "enable_dark_mode")
        assert client.get(url).status_code == 200
        entry.is_active = False
        entry.save()
        assert services.get_public("ui_feature_flag", "enable_dark_mode", default=None) is None
        assert client.get(url).status_code == 404
        assert client.get(set_url("ui_feature_flag")).json()["count"] == 0


@pytest.mark.django_db
class TestPublicConfigurationAdmin:
    """Admin stamps audit fields, warns that rows are public, and rejects secrets."""

    @pytest.fixture
    def staff_user(self):
        return User.objects.create_user(
            mobile_number="+919000000011",
            name="ops",
            email="ops-public@example.com",
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
        return PublicConfigurationAdmin(PublicConfiguration, AdminSite())

    def form_data(self, **overrides):
        return {
            "config_set": "UI_Feature_Flag",
            "config_key": "Enable_Dark_Mode",
            "value_type": "boolean",
            "config_value": "false",
            "is_active": "on",
            **overrides,
        }

    def test_save_model_stamps_audit_fields(self, model_admin, request_, staff_user):
        entry = PublicConfiguration(
            config_set="ui_feature_flag", config_key="enable_dark_mode", config_value="false"
        )
        model_admin.save_model(request_, entry, form=None, change=False)
        entry.refresh_from_db()
        assert entry.created_by == staff_user
        assert entry.updated_by == staff_user

    def test_audit_fields_are_read_only(self, model_admin, request_):
        readonly = model_admin.get_readonly_fields(request_)
        assert {"id", "created_at", "updated_at", "created_by", "updated_by"} <= set(readonly)

    def test_change_form_warns_that_rows_are_public(self, model_admin, request_):
        descriptions = [opts.get("description") for _, opts in model_admin.fieldsets]
        assert "Everything in this table is public and visible to internet clients." in (
            descriptions
        )

    def test_form_normalizes(self, model_admin, request_):
        form = model_admin.get_form(request_, obj=None)(data=self.form_data())
        assert form.is_valid(), form.errors
        assert form.instance.config_set == "ui_feature_flag"
        assert form.instance.config_key == "enable_dark_mode"

    def test_form_rejects_secret_like_key(self, model_admin, request_):
        data = self.form_data(config_key="gateway.password", value_type="string")
        form = model_admin.get_form(request_, obj=None)(data=data)
        assert not form.is_valid()
        assert "config_key" in form.errors

    def test_form_rejects_value_not_matching_type(self, model_admin, request_):
        data = self.form_data(value_type="integer", config_value="abc")
        form = model_admin.get_form(request_, obj=None)(data=data)
        assert not form.is_valid()
        assert "value_type" in form.errors
