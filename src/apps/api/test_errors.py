"""Tests for the standard error response and error code catalogue (spec 0000 section 9)."""

import importlib
import json
import uuid

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase, override_settings
from django.urls import include, path, reverse
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter
from rest_framework.test import APITestCase

from apps.api import errors
from apps.api.errors import BusinessError, define, error_items
from apps.api.schema import error_responses
from apps.api.serializers import AuditedModelSerializer
from apps.api.viewsets import APIModelViewSet
from apps.core.models import ApiVersionChangeLog
from apps.users.models import RegistrationStatus, User


class ChangeLogSerializer(AuditedModelSerializer):
    """Test-only serializer with a required field to fail on."""

    class Meta:
        """Meta options."""

        model = ApiVersionChangeLog
        fields = ["id", "version", "change_log", "additional_attributes"]


class ChangeLogViewSet(APIModelViewSet):
    """Test-only viewset on the shared base class, for the upsert action."""

    queryset = ApiVersionChangeLog.objects.all()
    serializer_class = ChangeLogSerializer


@api_view(["GET"])
@permission_classes([AllowAny])
def raise_django_validation_error(request):
    """Raise the way a model's full_clean() would from a service."""
    raise DjangoValidationError({"name": DjangoValidationError("Bad name.", code="max_length")})


def raise_unhandled(request):
    """A plain Django view that crashes."""
    raise RuntimeError("secret internals")


router = DefaultRouter()
router.register(r"changelogs", ChangeLogViewSet, basename="test-errors-changelog")
urlpatterns = [
    path("test-api/", include(router.urls)),
    path("api/django-validation/", raise_django_validation_error, name="django-validation"),
    path("api/boom/", raise_unhandled, name="boom"),
    path("boom/", raise_unhandled, name="boom-outside-api"),
]
handler404 = "apps.api.errors.handler404"
handler500 = "apps.api.errors.handler500"


class ErrorItemsTests(SimpleTestCase):
    """Flattening exception details into error items."""

    def test_business_error_carries_its_code_and_status(self):
        exc = BusinessError(errors.CONFLICT)
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(error_items(exc), [{"code": "E00108", "msg": errors.CONFLICT.msg}])

    def test_business_error_message_and_field_can_be_overridden(self):
        exc = BusinessError(errors.INVALID, "Wrong OTP", field="otp")
        self.assertEqual(error_items(exc), [{"code": "E00001", "msg": "Wrong OTP", "field": "otp"}])

    def test_drf_codes_are_mapped_to_registered_codes(self):
        exc = serializers.ValidationError({"name": [exceptions.ErrorDetail("x", code="required")]})
        self.assertEqual(error_items(exc), [{"code": "E00002", "msg": "x", "field": "name"}])

    def test_nested_fields_become_dotted_and_indexed_paths(self):
        exc = serializers.ValidationError(
            {
                "profile": {"bar_number": ["bad"]},
                "items": [{}, {"qty": ["too small"]}],
                "non_field_errors": ["whole object"],
            }
        )
        self.assertEqual(
            [(item.get("field"), item["msg"]) for item in error_items(exc)],
            [("profile.bar_number", "bad"), ("items[1].qty", "too small"), (None, "whole object")],
        )

    def test_unknown_code_falls_back_by_status(self):
        class Teapot(exceptions.APIException):
            status_code = 403
            default_code = "something_custom"

        self.assertEqual(error_items(Teapot())[0]["code"], errors.PERMISSION_DENIED.code)

    def test_empty_detail_still_yields_one_error(self):
        self.assertEqual(
            error_items(serializers.ValidationError({})),
            [{"code": "E00001", "msg": errors.INVALID.msg}],
        )

    def test_validation_error_helper_carries_the_code(self):
        exc = errors.CONFLICT.validation_error({"name": ["taken"]})
        self.assertEqual(error_items(exc), [{"code": "E00108", "msg": "taken", "field": "name"}])
        self.assertEqual(
            error_items(errors.CONFLICT.validation_error())[0]["msg"], errors.CONFLICT.msg
        )

    def test_error_responses_group_codes_by_their_status(self):
        documented = error_responses(errors.INVALID, errors.REQUIRED, errors.CONFLICT)
        self.assertEqual(set(documented), {400, 409})
        self.assertIn("`E00002`", documented[400].description)

    def test_field_prefix_is_applied(self):
        exc = serializers.ValidationError({"version": ["required"]})
        self.assertEqual(
            error_items(exc, field="datapoints[2]")[0]["field"], "datapoints[2].version"
        )


class ErrorRegistryTests(SimpleTestCase):
    """The catalogue rejects codes that would be ambiguous to clients."""

    def test_every_code_is_well_formed_and_unique(self):
        codes = [error.code for error in errors.all_errors()]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertRegex(code, errors.ERROR_CODE_PATTERN)

    def test_domain_codes_are_discovered(self):
        codes = {error.code for error in errors.all_errors()}
        self.assertIn("E01001", codes)  # apps.users.errors
        self.assertIn("E02001", codes)  # apps.dristi_requests.errors

    def test_duplicate_code_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            define("E00001", "Again.")

    def test_malformed_code_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            define("X1", "Bad.")

    def test_unallocated_domain_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            define("E99001", "Nobody owns 99.")

    def test_exception_classes_agree_with_their_registered_status(self):
        """An exception class's status is what clients get; the catalogue must match it."""
        # Load every module that defines coded exceptions, so none is skipped
        # just because no earlier test happened to import it.
        for module in (
            "apps.dristi_requests.exceptions",
            "apps.dristi_requests.views",
            "apps.users.views",
        ):
            importlib.import_module(module)

        def subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from subclasses(sub)

        checked = 0
        for exc_class in subclasses(exceptions.APIException):
            error = errors.get_error(exc_class.default_code)
            if error is not None:
                checked += 1
                self.assertEqual(exc_class.status_code, error.status, exc_class.__qualname__)
        self.assertGreaterEqual(checked, 6)


@override_settings(ROOT_URLCONF=__name__)
class ErrorResponseAPITests(APITestCase):
    """Error bodies as clients receive them."""

    def setUp(self):
        self.user = User.objects.create_user(
            mobile_number="+919000000011",
            password="test",
            registration_status=RegistrationStatus.COMPLETE,
        )

    def assert_error_body(self, response, code):
        payload = response.json()
        self.assertEqual(set(payload), {"errors", "meta"})
        self.assertEqual(payload["meta"]["spec_version"], "1.0")
        self.assertIn(code, [error["code"] for error in payload["errors"]])
        return payload["errors"]

    def test_not_found(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("test-errors-changelog-detail", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assert_error_body(response, "E00105")

    def test_unauthenticated(self):
        # Session authentication sends no WWW-Authenticate challenge, so DRF
        # answers 403. The code still tells "log in" apart from "not allowed".
        response = self.client.get(reverse("test-errors-changelog-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_error_body(response, "E00102")

    def test_malformed_json(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-errors-changelog-list"), "{not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_error_body(response, "E00101")

    def test_django_validation_error_is_a_400_not_a_500(self):
        response = self.client.get(reverse("django-validation"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        [error] = self.assert_error_body(response, "E00006")
        self.assertEqual(error, {"code": "E00006", "msg": "Bad name.", "field": "name"})

    def test_model_validation_on_save_is_reported_on_its_field(self):
        """BaseExtendableModel validates in save(); a shared CRUD create must not 500."""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-errors-changelog-list"),
            {"version": "1", "change_log": "x", "additional_attributes": {"nope": 1}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        [error] = self.assert_error_body(response, "E00001")
        self.assertEqual(error["field"], "additional_attributes")
        self.assertFalse(ApiVersionChangeLog.objects.exists())

    def test_unknown_api_route(self):
        response = self.client.get("/api/does-not-exist/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assert_error_body(response, "E00105")

    def test_unknown_route_outside_api_keeps_django_page(self):
        response = self.client.get("/does-not-exist/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(response["Content-Type"], "application/json")

    def test_unhandled_exception_under_api(self):
        self.client.raise_request_exception = False
        response = self.client.get(reverse("boom"))
        self.assertEqual(response.status_code, 500)
        self.assert_error_body(response, "E00100")
        self.assertNotIn("secret internals", response.content.decode())

    def test_unhandled_exception_outside_api_keeps_django_page(self):
        self.client.raise_request_exception = False
        response = self.client.get(reverse("boom-outside-api"))
        self.assertEqual(response.status_code, 500)
        self.assertNotEqual(response["Content-Type"], "application/json")

    def test_incomplete_registration_has_its_own_code(self):
        self.user.registration_status = RegistrationStatus.PENDING_PROFILE
        self.user.save()
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("test-errors-changelog-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_error_body(response, "E01006")

    def test_validation_errors_name_the_field(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(reverse("test-errors-changelog-list"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        errors_ = self.assert_error_body(response, "E00002")
        self.assertIn("version", [error.get("field") for error in errors_])

    def test_upsert_errors_are_attributed_to_their_datapoint(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-errors-changelog-upsert"),
            {"datapoints": [{"version": "1", "change_log": "ok"}, {"change_log": "x"}, 5]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        fields = {error["field"] for error in self.assert_error_body(response, "E00002")}
        self.assertEqual(fields, {"datapoints[1].version", "datapoints[2]"})
        self.assertFalse(ApiVersionChangeLog.objects.exists())

    def test_upsert_unknown_or_malformed_id_is_reported_not_a_500(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-errors-changelog-upsert"),
            {"datapoints": [{"id": str(uuid.uuid4()), "version": "1"}, {"id": "not-a-uuid"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        by_field = {error["field"]: error["code"] for error in response.json()["errors"]}
        self.assertEqual(by_field["datapoints[0]"], "E00105")
        self.assertEqual(by_field["datapoints[1]"], "E00001")


class ProjectUrlconfTests(APITestCase):
    """The real URL configuration has the API error handlers wired in."""

    def test_unknown_api_route_uses_the_standard_shape(self):
        response = self.client.get("/api/v1/does-not-exist/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["errors"][0]["code"], "E00105")
        self.assertIn("meta", response.json())


@override_settings(ROOT_URLCONF="config.urls")
class ErrorSchemaTests(APITestCase):
    """The error format and catalogue are part of the Swagger documentation."""

    def setUp(self):
        response = self.client.get(f"{reverse('api-schema')}?format=json")
        self.schema = json.loads(response.content)

    def test_error_response_component(self):
        item = self.schema["components"]["schemas"]["ErrorItem"]
        self.assertEqual(item["properties"]["code"]["enum"], [e.code for e in errors.all_errors()])
        self.assertIn("ErrorResponse", self.schema["components"]["schemas"])

    def test_catalogue_is_listed_in_the_description(self):
        description = self.schema["info"]["description"]
        for error in errors.all_errors():
            self.assertIn(f"| `{error.code}` | {error.status} |", description)

    def test_every_operation_documents_errors(self):
        for path_item in self.schema["paths"].values():
            for operation in path_item.values():
                self.assertEqual(
                    operation["responses"]["4XX"]["content"]["application/json"]["schema"],
                    {"$ref": "#/components/schemas/ErrorResponse"},
                )

    def test_declared_error_statuses_list_their_codes(self):
        responses = self.schema["paths"]["/api/v1/users/"]["post"]["responses"]
        self.assertIn("E01001", responses["401"]["description"])
        self.assertIn("ErrorResponse", json.dumps(responses["401"]["content"]))

    def test_workflow_business_errors_are_documented(self):
        decide = next(
            item["post"]
            for route, item in self.schema["paths"].items()
            if route.endswith("/decide/")
        )["responses"]
        self.assertIn("E02002", decide["400"]["description"])
        self.assertIn("E02004", decide["403"]["description"])
        self.assertIn("E02003", decide["409"]["description"])
