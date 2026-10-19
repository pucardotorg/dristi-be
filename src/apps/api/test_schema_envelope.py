"""The OpenAPI schema documents the ``meta`` envelope as responses really carry it (spec 0000 section 8)."""

import json

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.api.schema import META_REF, with_meta
from apps.locations.tests.factories import make_hierarchy

SCHEMA_PATH = "/api/schema/"


def load_schema(client):
    response = client.get(f"{reverse('api-schema')}?format=json")
    return json.loads(response.content)


def success_schema(schema, path, method="get", status_code="200"):
    response = schema["paths"][path][method]["responses"][status_code]
    return response["content"]["application/json"]["schema"]


def documented_keys(schema, body_schema):
    """Top-level keys a documented body must have, following $ref and allOf."""
    if "$ref" in body_schema:
        name = body_schema["$ref"].rsplit("/", 1)[-1]
        return documented_keys(schema, schema["components"]["schemas"][name])
    if "allOf" in body_schema:
        return set().union(*(documented_keys(schema, part) for part in body_schema["allOf"]))
    return set(body_schema.get("required", []))


class WithMetaTests(SimpleTestCase):
    """with_meta() mirrors MetaJSONRenderer."""

    def test_objects_gain_a_meta_property(self):
        wrapped = with_meta({"$ref": "#/components/schemas/Location"})
        self.assertEqual(wrapped["allOf"][0], {"$ref": "#/components/schemas/Location"})
        self.assertEqual(wrapped["allOf"][1]["properties"], {"meta": META_REF})

    def test_arrays_and_scalars_are_wrapped_in_data(self):
        for schema in ({"type": "array", "items": {}}, {"type": "string"}):
            wrapped = with_meta(schema)
            self.assertEqual(wrapped["properties"], {"data": schema, "meta": META_REF})
            self.assertEqual(wrapped["required"], ["data", "meta"])


@override_settings(ROOT_URLCONF="config.urls")
class SchemaEnvelopeTests(APITestCase):
    """Every JSON success response in the schema documents meta."""

    def setUp(self):
        self.schema = load_schema(self.client)

    def test_every_json_success_response_documents_meta(self):
        checked = 0
        for path, item in self.schema["paths"].items():
            if path == SCHEMA_PATH:  # served by spectacular's renderers, without meta
                continue
            for operation in item.values():
                for status_code, response in operation["responses"].items():
                    media = response.get("content", {}).get("application/json")
                    if status_code.startswith("2") and media:
                        self.assertIn("meta", documented_keys(self.schema, media["schema"]), path)
                        checked += 1
        self.assertGreater(checked, 30)

    def test_schema_endpoint_is_left_alone(self):
        self.assertNotIn("ResponseMeta", json.dumps(success_schema(self.schema, SCHEMA_PATH)))

    def test_meta_component_has_realistic_examples(self):
        meta = self.schema["components"]["schemas"]["ResponseMeta"]
        self.assertEqual(meta["required"], ["timestamp", "app_version", "spec_version"])
        self.assertTrue(meta["properties"]["timestamp"]["example"].endswith("+05:30"))
        self.assertEqual(meta["properties"]["spec_version"]["example"], "1.0")

    def test_error_responses_share_the_meta_component(self):
        error = self.schema["components"]["schemas"]["ErrorResponse"]
        self.assertEqual(error["properties"]["meta"], META_REF)


@override_settings(ROOT_URLCONF="config.urls")
class DocumentedShapeMatchesResponseTests(APITestCase):
    """The documented top-level keys are the ones the endpoint actually returns."""

    def setUp(self):
        self.schema = load_schema(self.client)
        self.india, self.bihar, self.patna = make_hierarchy()

    def assert_matches(self, url, path):
        body = self.client.get(url).json()
        expected = documented_keys(self.schema, success_schema(self.schema, path))
        self.assertTrue(expected <= set(body), f"{path}: documented {expected}, got {set(body)}")
        self.assertIn("meta", body)
        return body

    def test_object(self):
        self.assert_matches(
            reverse("location-detail", args=[self.bihar.pk]), "/api/v1/locations/{id}/"
        )

    def test_paginated_list(self):
        body = self.assert_matches(reverse("location-list"), "/api/v1/locations/")
        self.assertIn("results", body)

    def test_paginated_action(self):
        body = self.assert_matches(
            reverse("location-children", args=[self.india.pk]), "/api/v1/locations/{id}/children/"
        )
        self.assertIn("results", body)

    def test_unpaginated_list_is_wrapped_in_data(self):
        body = self.assert_matches(
            reverse("location-ancestors", args=[self.patna.pk]), "/api/v1/locations/{id}/ancestors/"
        )
        self.assertIsInstance(body["data"], list)

    def test_function_view(self):
        self.assert_matches(reverse("health"), "/api/v1/health/")


@override_settings(ROOT_URLCONF="config.urls")
class SchemaConventionTests(APITestCase):
    """ApiAutoSchema fills in what views would otherwise declare per operation."""

    def setUp(self):
        self.schema = load_schema(self.client)

    def operation(self, path, method="get"):
        return self.schema["paths"][path][method]

    def test_tag_defaults_to_the_owning_app(self):
        self.assertEqual(self.operation("/api/v1/organizations/{id}/")["tags"], ["organizations"])
        self.assertEqual(self.operation("/api/v1/health/")["tags"], ["core"])  # @api_view

    def test_explicit_tags_win(self):
        self.assertEqual(self.operation("/api/v1/sessions/", "post")["tags"], ["auth"])

    def test_list_actions_are_documented_as_paginated_lists(self):
        body = success_schema(self.schema, "/api/v1/organizations/{id}/children/")
        self.assertIn("results", documented_keys(self.schema, body))

    def test_list_action_uses_the_action_serializer(self):
        body = json.dumps(success_schema(self.schema, "/api/v1/organizations/{id}/jurisdictions/"))
        self.assertIn("Location", body)
        self.assertNotIn("Organization", body)

    def test_error_responses_alone_keep_the_inferred_success(self):
        body = success_schema(self.schema, "/api/v1/organizations/")
        self.assertIn("results", documented_keys(self.schema, body))
        responses = self.operation("/api/v1/organizations/")["responses"]
        self.assertIn("parent_id", json.dumps(responses["400"]))
