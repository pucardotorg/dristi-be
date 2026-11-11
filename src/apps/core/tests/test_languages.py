"""Tests for the Language model, its admin, caching and seed data (spec 0030)."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext

from apps.core.admin import LanguageAdmin, LanguageSupportFilter
from apps.core.languages import resolve_request_language
from apps.core.models import Language, validate_language_code

User = get_user_model()

# supports__contains is PostgreSQL-only (spec 0030 section 1); CI runs on PostgreSQL.
requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="JSONField contains needs PostgreSQL"
)


def make(code="ta", **kwargs):
    return Language.objects.create(
        code=code, name=kwargs.pop("name", "Tamil"), native_name="தமிழ்", **kwargs
    )


@pytest.mark.django_db
class TestLanguageCode:
    """Code format and normalisation."""

    @pytest.mark.parametrize("code", ["en", "ml", "en-in", "kok", "zh-hant-tw"])
    def test_valid_codes_accepted(self, code):
        validate_language_code(code)

    @pytest.mark.parametrize("code", ["EN_IN", "en_in", "e", "en-", "en\n", "english", "", "en-i"])
    def test_invalid_codes_rejected(self, code):
        with pytest.raises(ValidationError):
            validate_language_code(code)

    @pytest.mark.parametrize("code", ["EN_IN", "e", "en-", "en\n"])
    def test_full_clean_rejects_invalid_code(self, code):
        with pytest.raises(ValidationError) as exc:
            Language(code=code, name="X", native_name="X").full_clean()
        assert "code" in exc.value.message_dict

    def test_full_clean_accepts_and_lowercases_uppercase_code(self):
        language = Language(code="TA-IN", name="Tamil", native_name="தமிழ்")
        language.full_clean()
        assert language.code == "ta-in"

    def test_code_lowercased_on_save(self):
        language = make(code="TA-IN")
        language.refresh_from_db()
        assert language.code == "ta-in"

    def test_case_variants_cannot_coexist(self):
        make(code="ta-in")
        with pytest.raises(IntegrityError), transaction.atomic():
            make(code="TA-IN")

        with pytest.raises(ValidationError) as exc:
            Language(code="TA-IN", name="Tamil", native_name="தமிழ்").full_clean()
        assert "code" in exc.value.message_dict


@pytest.mark.django_db
class TestDefaultLanguage:
    """Exactly one active default that cannot be removed."""

    def test_get_default_returns_seeded_english(self):
        assert Language.objects.get_default().code == "en"

    def test_get_default_without_default_is_a_configuration_error(self):
        Language.objects.filter(is_default=True).update(is_default=False)
        with pytest.raises(ImproperlyConfigured):
            Language.objects.get_default()

    def test_second_default_rejected_by_database(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            make(is_default=True)

    def test_second_default_rejected_by_validation(self):
        with pytest.raises(ValidationError):
            Language(code="ta", name="Tamil", native_name="தமிழ்", is_default=True).full_clean()

    def test_default_cannot_be_inactive_in_database(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Language.objects.filter(code="en").update(is_active=False)

    def test_default_cannot_be_deactivated(self):
        language = Language.objects.get(code="en")
        language.is_active = False
        with pytest.raises(ValidationError) as exc:
            language.full_clean()
        assert "is_active" in exc.value.message_dict

    def test_default_cannot_be_undefaulted(self):
        language = Language.objects.get(code="en")
        language.is_default = False
        with pytest.raises(ValidationError) as exc:
            language.full_clean()
        assert "is_default" in exc.value.message_dict

    def test_new_language_may_be_default_when_none_exists(self):
        Language.objects.filter(is_default=True).update(is_default=False)
        Language(code="ta", name="Tamil", native_name="தமிழ்", is_default=True).full_clean()

    def test_default_cannot_be_deleted(self):
        with pytest.raises(ProtectedError):
            Language.objects.get(code="en").delete()
        with pytest.raises(ProtectedError):
            Language.objects.filter(code="en").delete()
        with pytest.raises(ProtectedError):
            Language.objects.all().delete()
        assert Language.objects.filter(code="en").exists()

    def test_stale_instance_of_new_default_cannot_be_deleted(self):
        # Loaded before the default moved to it, so its own is_default is stale.
        malayalam = Language.objects.get(code="ml")
        Language.objects.filter(code="en").update(is_default=False)
        Language.objects.filter(code="ml").update(is_default=True)
        with pytest.raises(ProtectedError):
            malayalam.delete()
        assert Language.objects.get_default().code == "ml"

    def test_stale_instance_of_former_default_can_be_deleted(self):
        english = Language.objects.get(code="en")
        Language.objects.filter(code="en").update(is_default=False)
        Language.objects.filter(code="ml").update(is_default=True)
        english.delete()
        assert not Language.objects.filter(code="en").exists()

    def test_other_languages_can_be_deleted(self):
        Language.objects.get(code="hi").delete()
        Language.objects.filter(code="ml").delete()
        assert list(Language.objects.values_list("code", flat=True)) == ["en"]


@pytest.mark.django_db
class TestSupports:
    """``supports`` holds distinct, known capabilities in enum order."""

    @pytest.mark.parametrize(
        "supports", [["bogus"], ["ui", "bogus"], "ui", {"ui": True}, None, ["ui", "ui"]]
    )
    def test_full_clean_rejects_invalid_supports(self, supports):
        language = Language(code="ta", name="Tamil", native_name="தமிழ்", supports=supports)
        with pytest.raises(ValidationError) as exc:
            language.full_clean()
        assert "supports" in exc.value.message_dict

    def test_full_clean_orders_supports(self):
        language = Language(code="ta", name="Tamil", native_name="தமிழ்", supports=["ocr", "ui"])
        language.full_clean()
        assert language.supports == ["ui", "ocr"]

    def test_empty_supports_is_content_only(self):
        language = Language(code="ta", name="Tamil", native_name="தமிழ்")
        language.full_clean()
        assert language.supports == []

    def test_save_normalises_to_enum_order(self):
        language = make(supports=["ocr", "ui", "ui", "translation"])
        language.refresh_from_db()
        assert language.supports == ["ui", "translation", "ocr"]

    def test_bulk_create_normalises_like_save(self):
        Language.objects.bulk_create(
            [
                Language(
                    code=" TA-IN ", name="Tamil", native_name="தமிழ்", supports=["ocr", "ui", "ui"]
                )
            ]
        )
        assert Language.objects.filter(code="ta-in", supports=["ui", "ocr"]).exists()

    def test_bulk_create_rejects_unknown_capability(self):
        with pytest.raises(ValidationError):
            Language.objects.bulk_create(
                [Language(code="ta", name="Tamil", native_name="தமிழ்", supports=["bogus"])]
            )
        assert not Language.objects.filter(code="ta").exists()

    def test_save_rejects_unknown_capability(self):
        with pytest.raises(ValidationError):
            make(supports=["bogus"])
        assert not Language.objects.filter(code="ta").exists()


@pytest.mark.django_db
class TestLanguageAdmin:
    """Admin form, filter, delete protection and the make-default action."""

    @pytest.fixture
    def staff_user(self):
        return User.objects.create_user(
            mobile_number="+919000000011",
            name="ops",
            email="ops-languages@example.com",
            password="x",
            is_staff=True,
            is_superuser=True,
        )

    @pytest.fixture
    def request_(self, staff_user):
        request = RequestFactory().post("/admin/")
        request.user = staff_user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    @pytest.fixture
    def model_admin(self):
        return LanguageAdmin(Language, AdminSite())

    def form_data(self, **overrides):
        data = {
            "code": "TA",
            "name": "Tamil",
            "native_name": "தமிழ்",
            "supports": ["ocr", "ui"],
            "sort_order": "30",
            "is_active": "on",
        }
        data.update(overrides)
        return {key: value for key, value in data.items() if value is not None}

    def test_form_maps_checkboxes_to_json_list(self, model_admin, request_, staff_user):
        form = model_admin.get_form(request_, obj=None)(data=self.form_data())
        assert form.is_valid(), form.errors
        language = form.save(commit=False)
        model_admin.save_model(request_, language, form, change=False)
        language.refresh_from_db()
        assert language.code == "ta"
        assert language.supports == ["ui", "ocr"]
        assert language.created_by == staff_user

    def test_form_shows_stored_supports_as_checked(self, model_admin, request_):
        language = make(supports=["ui", "ocr"])
        form = model_admin.get_form(request_, obj=language)(instance=language)
        assert form["supports"].initial == ["ui", "ocr"]

    def test_form_rejects_unknown_capability(self, model_admin, request_):
        form = model_admin.get_form(request_, obj=None)(data=self.form_data(supports=["bogus"]))
        assert not form.is_valid()
        assert "supports" in form.errors

    def test_form_rejects_deactivating_default(self, model_admin, request_):
        english = Language.objects.get(code="en")
        form_class = model_admin.get_form(request_, obj=english)
        data = self.form_data(code="en", name="English", native_name="English", is_active=None)
        form = form_class(data={**data, "is_default": "on"}, instance=english)
        assert not form.is_valid()
        assert "is_active" in form.errors

    def test_form_rejects_undefaulting_default(self, model_admin, request_):
        english = Language.objects.get(code="en")
        form_class = model_admin.get_form(request_, obj=english)
        data = self.form_data(code="en", name="English", native_name="English")
        form = form_class(data=data, instance=english)
        assert not form.is_valid()
        assert "is_default" in form.errors

    def test_changelist_form_rejects_deactivating_default(self, model_admin, request_):
        english = Language.objects.get(code="en")
        form_class = model_admin.get_changelist_form(request_, fields=model_admin.list_editable)
        form = form_class(data={"sort_order": "0"}, instance=english)
        assert not form.is_valid()
        assert "is_active" in form.errors

    def test_default_has_no_delete_permission(self, model_admin, request_):
        assert not model_admin.has_delete_permission(request_, Language.objects.get(code="en"))
        assert model_admin.has_delete_permission(request_, Language.objects.get(code="ml"))

    @requires_postgres
    def test_supports_filter(self, model_admin, request_):
        make(supports=["ocr"])
        list_filter = LanguageSupportFilter(request_, {"supports": ["ocr"]}, Language, model_admin)
        filtered = list_filter.queryset(request_, Language.objects.all())
        assert list(filtered.values_list("code", flat=True)) == ["ta"]

    def test_make_default_moves_the_flag(self, model_admin, request_, staff_user):
        model_admin.make_default(request_, Language.objects.filter(code="ml"))
        assert Language.objects.get_default().code == "ml"
        assert Language.objects.filter(is_default=True).count() == 1
        assert Language.objects.get(code="ml").updated_by == staff_user

    def test_make_default_refuses_inactive_or_several(self, model_admin, request_):
        make(is_active=False)
        model_admin.make_default(request_, Language.objects.filter(code="ta"))
        model_admin.make_default(request_, Language.objects.filter(code__in=["ml", "hi"]))
        assert Language.objects.get_default().code == "en"


@pytest.mark.django_db
class TestLanguageCaching:
    """Language reads are cachalot-cached and invalidated on write."""

    def test_table_is_cachable(self):
        from cachalot.settings import cachalot_settings

        assert "core_language" in cachalot_settings.CACHALOT_ONLY_CACHABLE_TABLES

    def test_list_reads_are_cached_and_invalidated_on_write(self):
        list(Language.objects.active())
        with CaptureQueriesContext(connection) as cached:
            list(Language.objects.active())
        assert len(cached.captured_queries) == 0

        make()
        with CaptureQueriesContext(connection) as after_write:
            codes = [language.code for language in Language.objects.active()]
        assert len(after_write.captured_queries) >= 1
        assert "ta" in codes

    def test_resolver_reads_are_cached_and_invalidated_on_write(self):
        request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE="ta")
        assert resolve_request_language(request).code == "en"
        with CaptureQueriesContext(connection) as cached:
            assert resolve_request_language(request).code == "en"
        assert len(cached.captured_queries) == 0

        make()
        assert resolve_request_language(request).code == "ta"

        Language.objects.filter(code="ta").update(is_active=False)
        assert resolve_request_language(request).code == "en"


@pytest.mark.django_db
class TestSeededLanguages:
    """The data migration seeds English (default), Malayalam and Hindi."""

    def test_seeding_is_idempotent_and_restores_values(self):
        migration = importlib.import_module("apps.core.migrations.0008_seed_languages")
        Language.objects.filter(code="hi").update(name="Changed", sort_order=99)
        migration.seed_languages(django_apps, None)
        migration.seed_languages(django_apps, None)
        assert Language.objects.count() == 3
        assert Language.objects.get(code="hi").name == "Hindi"
        assert Language.objects.get(code="hi").sort_order == 20

    def test_seeded_rows(self):
        rows = list(
            Language.objects.values_list(
                "code", "name", "native_name", "is_default", "sort_order", "is_active", "supports"
            )
        )
        assert rows == [
            ("en", "English", "English", True, 0, True, ["ui"]),
            ("ml", "Malayalam", "മലയാളം", False, 10, True, ["ui"]),
            ("hi", "Hindi", "हिन्दी", False, 20, True, ["ui"]),
        ]


@pytest.mark.django_db
class TestLanguageAdminViews:
    """The same rules, driven through the admin's own views."""

    CHANGELIST = "/admin/core/language/"

    @pytest.fixture
    def admin_client(self):
        user = User.objects.create_user(
            mobile_number="+919000000012",
            name="admin",
            email="admin-languages@example.com",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        client = Client()
        client.force_login(user)
        return client

    def changelist_data(self, **active):
        """A changelist (list_editable) POST for the three seeded languages."""
        languages = list(Language.objects.all())
        data = {
            "form-TOTAL_FORMS": str(len(languages)),
            "form-INITIAL_FORMS": str(len(languages)),
            "_save": "Save",
        }
        for index, language in enumerate(languages):
            data[f"form-{index}-id"] = str(language.pk)
            data[f"form-{index}-sort_order"] = str(language.sort_order)
            if active.get(language.code, language.is_active):
                data[f"form-{index}-is_active"] = "on"
        return data

    @pytest.mark.parametrize("query", ["", "?is_active__exact=1", "?q=mal"])
    def test_changelist_renders(self, admin_client, query):
        response = admin_client.get(self.CHANGELIST + query)
        assert response.status_code == 200
        assert "Malayalam" in response.content.decode() or query == "?is_active__exact=1"

    @requires_postgres
    def test_changelist_supports_filter_renders(self, admin_client):
        response = admin_client.get(self.CHANGELIST + "?supports=ui")
        assert response.status_code == 200

    def test_add_and_change_forms_render(self, admin_client):
        english = Language.objects.get(code="en")
        assert admin_client.get(f"{self.CHANGELIST}add/").status_code == 200
        response = admin_client.get(f"{self.CHANGELIST}{english.pk}/change/")
        assert response.status_code == 200
        assert 'type="checkbox" name="supports" value="ui"' in response.content.decode()

    def test_changelist_cannot_deactivate_default(self, admin_client):
        response = admin_client.post(self.CHANGELIST, self.changelist_data(en=False))
        assert response.status_code == 200
        assert "The default language cannot be deactivated." in response.content.decode()
        assert Language.objects.get(code="en").is_active

    def test_changelist_can_deactivate_other_language(self, admin_client):
        response = admin_client.post(self.CHANGELIST, self.changelist_data(hi=False))
        assert response.status_code == 302
        assert not Language.objects.get(code="hi").is_active

    def test_add_second_default_is_a_form_error(self, admin_client):
        data = {
            "code": "ta",
            "name": "Tamil",
            "native_name": "தமிழ்",
            "is_default": "on",
            "is_active": "on",
            "sort_order": "30",
        }
        response = admin_client.post(f"{self.CHANGELIST}add/", data)
        assert response.status_code == 200
        assert "Another language is already the default." in response.content.decode()
        assert not Language.objects.filter(code="ta").exists()

    def test_default_delete_page_is_forbidden(self, admin_client):
        english = Language.objects.get(code="en")
        assert admin_client.get(f"{self.CHANGELIST}{english.pk}/delete/").status_code == 403

    def test_bulk_delete_including_default_is_refused(self, admin_client):
        selected = [str(pk) for pk in Language.objects.values_list("pk", flat=True)]
        response = admin_client.post(
            self.CHANGELIST,
            {"action": "delete_selected", "_selected_action": selected, "post": "yes"},
        )
        assert response.status_code == 403
        assert Language.objects.count() == 3

    def test_make_default_action(self, admin_client):
        hindi = Language.objects.get(code="hi")
        response = admin_client.post(
            self.CHANGELIST, {"action": "make_default", "_selected_action": [str(hindi.pk)]}
        )
        assert response.status_code == 302
        assert Language.objects.get_default().code == "hi"
