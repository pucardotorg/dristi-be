"""Tests for the standard error response and error code catalogue (spec 0000 section 9)."""

import importlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, RequestDataTooBig, SuspiciousOperation
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase, override_settings
from django.urls import include, path, reverse
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.test import APITestCase

from apps.api import errors
from apps.api.errors import BusinessError, define, error_items
from apps.api.schema import ErrorScenario, _examples, error_responses
from apps.api.serializers import AuditedModelSerializer
from apps.api.viewsets import APIModelViewSet
from apps.api.viewsets.base import batch_error_status
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

    def authorize_update(self, serializer, model_instance):
        """Refuse updates to a 'locked' entry, to exercise permission failures."""
        if model_instance.version == "locked":
            raise exceptions.PermissionDenied()


@api_view(["GET"])
@permission_classes([AllowAny])
def raise_django_validation_error(request):
    """Raise the way a model's full_clean() would from a service."""
    raise DjangoValidationError({"name": DjangoValidationError("Bad name.", code="max_length")})


@api_view(["GET"])
@permission_classes([AllowAny])
def raise_django_non_field_error(request):
    """Raise the way a model's clean() reports an error on the whole object."""
    raise DjangoValidationError({"__all__": ["Bad combination."], "name": ["Bad name."]})


@api_view(["GET"])
@permission_classes([AllowAny])
def raise_suspicious(request):
    """DRF does not handle SuspiciousOperation; Django turns it into a 400."""
    raise SuspiciousOperation("secret internals")


@api_view(["GET"])
@permission_classes([AllowAny])
def raise_too_big(request):
    """Raise the way Django does for a body over DATA_UPLOAD_MAX_MEMORY_SIZE."""
    raise RequestDataTooBig("secret internals")


@api_view(["POST"])
@permission_classes([AllowAny])
def read_body(request):
    """Parse the request body, so Django's upload limits apply."""
    return Response(dict(request.data))


def raise_permission_denied(request):
    """A plain Django view (or middleware) refusing the request."""
    raise DjangoPermissionDenied("secret internals")


def raise_unhandled(request):
    """A plain Django view that crashes."""
    raise RuntimeError("secret internals")


router = DefaultRouter()
router.register(r"changelogs", ChangeLogViewSet, basename="test-errors-changelog")
urlpatterns = [
    path("test-api/", include(router.urls)),
    path("api/django-validation/", raise_django_validation_error, name="django-validation"),
    path("api/django-non-field/", raise_django_non_field_error, name="django-non-field"),
    path("api/suspicious/", raise_suspicious, name="suspicious"),
    path("suspicious/", raise_suspicious, name="suspicious-outside-api"),
    path("api/too-big/", raise_too_big, name="too-big"),
    path("api/read-body/", read_body, name="read-body"),
    path("api/forbidden/", raise_permission_denied, name="forbidden"),
    path("forbidden/", raise_permission_denied, name="forbidden-outside-api"),
    path("api/boom/", raise_unhandled, name="boom"),
    path("boom/", raise_unhandled, name="boom-outside-api"),
]
handler400 = "apps.api.errors.handler400"
handler403 = "apps.api.errors.handler403"
handler404 = "apps.api.errors.handler404"
handler500 = "apps.api.errors.handler500"


class ErrorItemsTests(SimpleTestCase):
    """Flattening exception details into error items."""

    def test_business_error_carries_its_code_and_status(self):
        exc = BusinessError(errors.CONFLICT)
        self.assertEqual(exc.status_code, 409)
        self.assertEqual(error_items(exc), [{"code": "E00108", "message": errors.CONFLICT.message}])

    def test_business_error_message_and_field_can_be_overridden(self):
        exc = BusinessError(errors.INVALID, "Wrong OTP", field="otp")
        self.assertEqual(
            error_items(exc), [{"code": "E00001", "message": "Wrong OTP", "field": "otp"}]
        )

    def test_drf_codes_are_mapped_to_registered_codes(self):
        exc = serializers.ValidationError({"name": [exceptions.ErrorDetail("x", code="required")]})
        self.assertEqual(error_items(exc), [{"code": "E00002", "message": "x", "field": "name"}])

    def test_nested_fields_become_dotted_and_indexed_paths(self):
        exc = serializers.ValidationError(
            {
                "profile": {"bar_number": ["bad"]},
                "items": [{}, {"qty": ["too small"]}],
                "non_field_errors": ["whole object"],
            }
        )
        self.assertEqual(
            [(item.get("field"), item["message"]) for item in error_items(exc)],
            [("profile.bar_number", "bad"), ("items[1].qty", "too small"), (None, "whole object")],
        )

    def test_unknown_code_falls_back_by_status(self):
        class Teapot(exceptions.APIException):
            status_code = 403
            default_code = "something_custom"

        self.assertEqual(error_items(Teapot())[0]["code"], errors.PERMISSION_DENIED.code)

    def test_unmapped_client_status_never_gets_a_server_error_code(self):
        class Unprocessable(exceptions.APIException):
            status_code = 422
            default_code = "something_custom"

        self.assertEqual(error_items(Unprocessable())[0]["code"], errors.INVALID.code)
        empty = Unprocessable(detail={})
        self.assertEqual(error_items(empty)[0]["code"], errors.INVALID.code)

    def test_unknown_too_large_status_gets_the_too_large_code(self):
        class TooLarge(exceptions.APIException):
            status_code = 413
            default_code = "something_custom"

        self.assertEqual(error_items(TooLarge())[0]["code"], errors.REQUEST_TOO_LARGE.code)

    def test_unmapped_server_status_gets_the_server_error_code(self):
        class Unavailable(exceptions.APIException):
            status_code = 503
            default_code = "something_custom"

        self.assertEqual(error_items(Unavailable())[0]["code"], errors.SERVER_ERROR.code)

    def test_empty_detail_still_yields_one_error(self):
        self.assertEqual(
            error_items(serializers.ValidationError({})),
            [{"code": "E00001", "message": errors.INVALID.message}],
        )

    def test_validation_error_helper_carries_the_code(self):
        exc = errors.CONFLICT.validation_error({"name": ["taken"]})
        self.assertEqual(
            error_items(exc), [{"code": "E00108", "message": "taken", "field": "name"}]
        )
        self.assertEqual(
            error_items(errors.CONFLICT.validation_error())[0]["message"], errors.CONFLICT.message
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


class BatchErrorStatusTests(SimpleTestCase):
    """The status of an aggregated upsert failure."""

    def test_uniform_failures_keep_their_status(self):
        self.assertEqual(batch_error_status([403, 403]), 403)
        self.assertEqual(batch_error_status([404]), 404)

    def test_mixed_client_failures_are_a_400(self):
        self.assertEqual(batch_error_status([400, 404, 409]), 400)

    def test_mixed_failures_follow_the_precedence(self):
        self.assertEqual(batch_error_status([400, 403]), 403)
        self.assertEqual(batch_error_status([400, 403, 401]), 401)
        self.assertEqual(batch_error_status([400, 401, 503]), 500)


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
            terms_version_accepted=settings.CURRENT_TERMS_VERSION,
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
        self.assertEqual(error, {"code": "E00006", "message": "Bad name.", "field": "name"})

    def test_django_non_field_error_carries_no_field(self):
        """Django files whole-object errors under "__all__"; that is not a field."""
        response = self.client.get(reverse("django-non-field"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            [(error.get("field"), error["message"]) for error in response.json()["errors"]],
            [(None, "Bad combination."), ("name", "Bad name.")],
        )

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

    def test_bad_request_django_handles_under_api(self):
        response = self.client.get(reverse("suspicious"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_error_body(response, "E00101")
        self.assertNotIn("secret internals", response.content.decode())

    def test_request_too_big_has_its_own_code_and_status(self):
        response = self.client.get(reverse("too-big"))
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assert_error_body(response, "E00111")
        self.assertNotIn("secret internals", response.content.decode())

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10)
    def test_oversized_multipart_body_is_413(self):
        response = self.client.post(reverse("read-body"), {"note": "x" * 100})
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assert_error_body(response, "E00111")

    def test_bad_request_outside_api_keeps_django_page(self):
        response = self.client.get(reverse("suspicious-outside-api"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotEqual(response["Content-Type"], "application/json")

    def test_permission_denied_django_handles_under_api(self):
        response = self.client.get(reverse("forbidden"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_error_body(response, "E00104")
        self.assertNotIn("secret internals", response.content.decode())

    def test_permission_denied_outside_api_keeps_django_page(self):
        response = self.client.get(reverse("forbidden-outside-api"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
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

    def test_upsert_permission_failure_keeps_its_403(self):
        locked = ApiVersionChangeLog.objects.create(version="locked", change_log="x")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-errors-changelog-upsert"),
            {"datapoints": [{"id": str(locked.pk), "version": "locked", "change_log": "y"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        [error] = self.assert_error_body(response, "E00104")
        self.assertEqual(error["field"], "datapoints[0]")

    def test_upsert_mixed_permission_and_validation_failures(self):
        """Every failure is still reported; the permission failure sets the status."""
        locked = ApiVersionChangeLog.objects.create(version="locked", change_log="x")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-errors-changelog-upsert"),
            {
                "datapoints": [
                    {"change_log": "missing version"},
                    {"id": str(locked.pk), "version": "locked", "change_log": "y"},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        by_field = {error["field"]: error["code"] for error in response.json()["errors"]}
        self.assertEqual(by_field["datapoints[0].version"], "E00002")
        self.assertEqual(by_field["datapoints[1]"], "E00104")
        locked.refresh_from_db()
        self.assertEqual(locked.change_log, "x")


class ProjectUrlconfTests(APITestCase):
    """The real URL configuration has the API error handlers wired in."""

    def test_unknown_api_route_uses_the_standard_shape(self):
        response = self.client.get("/api/v1/does-not-exist/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["errors"][0]["code"], "E00105")
        self.assertIn("meta", response.json())

    def test_every_django_error_handler_is_the_api_one(self):
        from config import urls

        for status_code in (400, 403, 404, 500):
            self.assertEqual(
                getattr(urls, f"handler{status_code}"), f"apps.api.errors.handler{status_code}"
            )


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


def operation_examples(schema, path, method):
    """Return {status: {example name: example}} for one operation."""
    responses = schema["paths"][path][method]["responses"]
    return {
        status_code: response["content"]["application/json"]["examples"]
        for status_code, response in responses.items()
        if "examples" in response.get("content", {}).get("application/json", {})
    }


@override_settings(ROOT_URLCONF="config.urls")
class ErrorExampleTests(APITestCase):
    """Each operation shows its own error scenarios as named examples."""

    def setUp(self):
        response = self.client.get(f"{reverse('api-schema')}?format=json")
        self.schema = json.loads(response.content)

    def test_no_shared_sample_built_from_property_examples(self):
        """Property-level examples made one generic sample for every endpoint."""
        item = self.schema["components"]["schemas"]["ErrorItem"]
        for prop in item["properties"].values():
            self.assertNotIn("example", prop)

    def test_every_example_is_well_formed_and_under_its_codes_status(self):
        checked = 0
        for route, item in self.schema["paths"].items():
            for method in item:
                for status_code, examples in operation_examples(self.schema, route, method).items():
                    for name, example in examples.items():
                        value = example["value"]
                        self.assertEqual(set(value), {"errors", "meta"}, name)
                        [error] = value["errors"]
                        registered = errors.get_error(error["code"])
                        self.assertIsNotNone(registered, name)
                        self.assertTrue(name.startswith(error["code"]), name)
                        self.assertEqual(example["summary"], error["message"])
                        # Not-authenticated is the one status DRF decides at runtime.
                        if error["code"] != errors.NOT_AUTHENTICATED.code:
                            self.assertEqual(int(status_code), registered.status, (route, name))
                        checked += 1
        self.assertGreater(checked, 30)

    def test_business_errors_with_their_fields(self):
        examples = operation_examples(self.schema, "/api/v1/litigants/", "post")
        email = examples["400"]["E01009 (email)"]["value"]["errors"][0]
        self.assertEqual(
            email,
            {"code": "E01009", "message": errors.get_error("E01009").message, "field": "email"},
        )
        self.assertIn("E01004", examples["409"])

    def test_power_of_attorney_registration_declares_its_errors(self):
        examples = operation_examples(self.schema, "/api/v1/power-of-attorneys/", "post")
        self.assertIn("E01009 (email)", examples["400"])
        self.assertIn("E01004", examples["409"])
        self.assertIn("E00102", examples["403"])

    def test_validation_example_names_a_real_required_field(self):
        examples = operation_examples(self.schema, "/api/v1/users/", "post")
        self.assertIn("E00002 (mobile_number)", examples["400"])
        self.assertIn("E01001", examples["401"])
        self.assertIn("E01002", examples["409"])

    def test_authenticated_endpoint_shows_not_authenticated_as_403(self):
        examples = operation_examples(self.schema, "/api/v1/litigants/", "post")
        self.assertIn("E00102", examples["403"])

    def test_public_endpoints_show_no_authentication_error(self):
        otp = operation_examples(self.schema, "/api/v1/auth/otp/request/", "post")
        self.assertNotIn("403", otp)
        # IsAuthenticatedOrReadOnly: reads are public.
        location = operation_examples(self.schema, "/api/v1/locations/{id}/", "get")
        self.assertNotIn("403", location)

    def test_detail_routes_show_not_found_naming_the_model(self):
        examples = operation_examples(self.schema, "/api/v1/locations/{id}/", "get")
        self.assertEqual(
            examples["404"]["E00105"]["summary"], "No Location matches the given query."
        )

    def test_query_parameter_errors_use_the_real_messages(self):
        examples = operation_examples(self.schema, "/api/v1/locations/", "get")["400"]
        self.assertEqual(examples["E00001 (parent_id)"]["summary"], "Must be a valid UUID.")
        self.assertIn("mutually exclusive", examples["E00001"]["summary"])

    def test_list_success_response_stays_paginated(self):
        list_200 = self.schema["paths"]["/api/v1/locations/"]["get"]["responses"]["200"]
        self.assertIn("Paginated", json.dumps(list_200))


class DefaultPermissionExampleTests(SimpleTestCase):
    """A view on the project's default permissions documents the registration gate."""

    def test_coded_permission_classes_become_examples(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
        examples = operation_examples(schema, "/test-api/changelogs/", "get")
        self.assertIn("E00102", examples["403"])
        self.assertIn("E01006", examples["403"])

    def test_repeated_codes_get_distinct_example_names(self):
        examples = _examples(
            [
                ErrorScenario(errors.INVALID, "first"),
                ErrorScenario(errors.INVALID, "second"),
            ]
        )
        self.assertEqual(list(examples), ["E00001", "E00001 #2"])
