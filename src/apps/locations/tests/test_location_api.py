"""Tests for the read-only Location API."""

import uuid
from datetime import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.api import errors
from apps.locations.tests.factories import make_hierarchy, make_state
from apps.users.models import User


class LocationAPITestCase(APITestCase):
    """Shared fixtures for the location endpoints."""

    def setUp(self):
        """Create the IN -> BR -> PATNA chain plus an inactive sibling state."""
        self.india, self.bihar, self.patna = make_hierarchy()
        self.goa = make_state(parent=self.india, code="GA", name="Goa", is_active=False)

    def assert_errors(self, response, expected):
        """Assert a 400 whose errors are exactly ``expected`` (code, field) pairs."""
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            [(e["code"], e.get("field")) for e in response.json()["errors"]],
            expected,
        )

    def assert_meta(self, payload):
        """Assert the API response includes the required metadata envelope."""
        self.assertIn("meta", payload)
        self.assertEqual(payload["meta"]["spec_version"], "1.0")
        self.assertIn("app_version", payload["meta"])
        self.assertIn("timestamp", payload["meta"])
        parsed = datetime.fromisoformat(payload["meta"]["timestamp"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(payload["meta"]["timestamp"][-6:], "+05:30")


class LocationListTests(LocationAPITestCase):
    """GET /api/v1/locations/"""

    def test_lists_all_locations(self):
        response = self.client.get(reverse("location-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 4)
        self.assert_meta(body)

    def test_filters_by_location_type(self):
        response = self.client.get(reverse("location-list"), {"location_type": "state"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR", "GA"})

    def test_filters_by_parent_code(self):
        response = self.client.get(reverse("location-list"), {"parent_code": "IN"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR", "GA"})

    def test_filters_by_parent_id_and_location_type(self):
        response = self.client.get(
            reverse("location-list"),
            {"parent_id": str(self.bihar.pk), "location_type": "district"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([row["code"] for row in results], ["PATNA"])

    def test_filters_by_is_active(self):
        response = self.client.get(reverse("location-list"), {"is_active": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([row["code"] for row in results], ["GA"])

    def test_rejects_both_parent_filters(self):
        response = self.client.get(
            reverse("location-list"),
            {"parent_id": str(self.india.pk), "parent_code": "IN"},
        )

        self.assert_errors(response, [(errors.INVALID.code, None)])

    def test_rejects_unknown_location_type(self):
        response = self.client.get(reverse("location-list"), {"location_type": "tehsil"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            [{"code": e["code"], "field": e.get("field")} for e in response.json()["errors"]],
            [{"code": "E00005", "field": "location_type"}],
        )

    def test_rejects_malformed_parent_id(self):
        response = self.client.get(reverse("location-list"), {"parent_id": "not-a-uuid"})

        self.assert_errors(response, [(errors.INVALID.code, "parent_id")])

    def test_rejects_unknown_parent_code(self):
        response = self.client.get(reverse("location-list"), {"parent_code": "NOPE"})

        self.assert_errors(response, [(errors.INVALID.code, "parent_code")])

    def test_rejects_non_boolean_is_active(self):
        for value in ("maybe", "1", "yes"):
            with self.subTest(value=value):
                response = self.client.get(reverse("location-list"), {"is_active": value})

                self.assert_errors(response, [(errors.INVALID.code, "is_active")])

    def test_empty_filter_values_are_ignored(self):
        response = self.client.get(
            reverse("location-list"),
            {"location_type": "", "parent_id": "", "is_active": ""},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 4)

    def test_is_active_is_case_and_whitespace_insensitive(self):
        for value in ("FALSE", " false "):
            with self.subTest(value=value):
                response = self.client.get(reverse("location-list"), {"is_active": value})

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                codes = [row["code"] for row in response.json()["results"]]
                self.assertEqual(codes, ["GA"])

    def test_reports_every_invalid_filter_at_once(self):
        response = self.client.get(
            reverse("location-list"),
            {"location_type": "tehsil", "parent_id": "bad", "is_active": "maybe"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            {(e["code"], e.get("field")) for e in response.json()["errors"]},
            {
                (errors.INVALID_CHOICE.code, "location_type"),
                (errors.INVALID.code, "parent_id"),
                (errors.INVALID.code, "is_active"),
            },
        )

    def test_filters_apply_to_detail_lookup_by_id(self):
        url = reverse("location-detail", args=[self.goa.pk])

        self.assertEqual(self.client.get(url, {"is_active": "false"}).status_code, 200)
        self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 404)
        self.assert_errors(
            self.client.get(url, {"is_active": "maybe"}), [(errors.INVALID.code, "is_active")]
        )


class LocationRetrieveTests(LocationAPITestCase):
    """GET /api/v1/locations/{id}/ and /locations/code/{code}/"""

    def test_retrieve_by_id(self):
        response = self.client.get(reverse("location-detail", args=[self.patna.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["code"], "PATNA")
        self.assert_meta(body)

    def test_retrieve_by_code(self):
        response = self.client.get(reverse("location-by-code", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.patna.pk))

    def test_serialized_payload_includes_parent_code_and_full_name(self):
        response = self.client.get(reverse("location-by-code", args=["PATNA"]))

        body = response.json()
        self.assertEqual(body["parent"], str(self.bihar.pk))
        self.assertEqual(body["parent_code"], "BR")
        self.assertEqual(body["full_name"], "India / Bihar / Patna")
        self.assertTrue(body["is_active"])
        self.assertEqual(body["additional_attributes"], {})

    def test_root_has_null_parent_code(self):
        response = self.client.get(reverse("location-by-code", args=["IN"]))

        body = response.json()
        self.assertIsNone(body["parent"])
        self.assertIsNone(body["parent_code"])
        self.assertEqual(body["full_name"], "India")

    def test_unknown_id_returns_404(self):
        response = self.client.get(reverse("location-detail", args=[uuid.uuid4()]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_code_returns_404(self):
        response = self.client.get(reverse("location-by-code", args=["NOPE"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LocationChildrenTests(LocationAPITestCase):
    """GET /locations/{id}/children/ and /locations/code/{code}/children/"""

    def test_children_by_id(self):
        response = self.client.get(reverse("location-children", args=[self.india.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        codes = {row["code"] for row in body["results"]}
        self.assertEqual(codes, {"BR"})
        self.assert_meta(body)

    def test_children_by_code(self):
        response = self.client.get(reverse("location-by-code-children", args=["IN"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR"})

    def test_children_are_direct_only(self):
        response = self.client.get(reverse("location-by-code-children", args=["IN"]))

        codes = {row["code"] for row in response.json()["results"]}
        self.assertNotIn("PATNA", codes)

    def test_leaf_has_no_children(self):
        response = self.client.get(reverse("location-by-code-children", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_children_of_unknown_code_returns_404(self):
        response = self.client.get(reverse("location-by-code-children", args=["NOPE"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def children_urls(self, location):
        """Return the by-id and by-code children URLs of ``location``."""
        return [
            reverse("location-children", args=[location.pk]),
            reverse("location-by-code-children", args=[location.code]),
        ]

    def test_children_filter_by_location_type_on_both_routes(self):
        # IN is a country: the filter describes the children, not the parent.
        for url in self.children_urls(self.india):
            with self.subTest(url=url):
                response = self.client.get(url, {"location_type": "state"})

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                codes = {row["code"] for row in response.json()["results"]}
                self.assertEqual(codes, {"BR"})

    def test_children_filter_by_location_type_may_narrow_to_none(self):
        for url in self.children_urls(self.bihar):
            with self.subTest(url=url):
                response = self.client.get(url, {"location_type": "state"})

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.json()["count"], 0)

    def test_children_of_inactive_parent_are_not_found_on_both_routes(self):
        for url in self.children_urls(self.goa):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    def test_children_reject_invalid_location_type_on_both_routes(self):
        for url in self.children_urls(self.india):
            with self.subTest(url=url):
                response = self.client.get(url, {"location_type": "tehsil"})

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    [
                        {"code": e["code"], "field": e.get("field")}
                        for e in response.json()["errors"]
                    ],
                    [{"code": "E00005", "field": "location_type"}],
                )

    def test_children_reject_parent_filters_on_both_routes(self):
        for url in self.children_urls(self.india):
            for params in (
                {"parent_id": str(self.bihar.pk)},
                {"parent_id": "not-a-uuid"},
                {"parent_code": "BR"},
            ):
                with self.subTest(url=url, params=params):
                    self.assert_errors(self.client.get(url, params), [(errors.INVALID.code, None)])

    def test_children_accept_is_active_true_as_a_no_op_on_both_routes(self):
        # Only active children are ever listed, so true asks for the default.
        for url in self.children_urls(self.india):
            for params in (
                {"is_active": "true"},
                {"is_active": " TRUE "},
                {"is_active": "true", "location_type": "state"},
            ):
                with self.subTest(url=url, params=params):
                    response = self.client.get(url, params)

                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    codes = {row["code"] for row in response.json()["results"]}
                    self.assertEqual(codes, {"BR"})

    def test_children_is_active_true_on_inactive_parent_is_not_found(self):
        for url in self.children_urls(self.goa):
            with self.subTest(url=url):
                response = self.client.get(url, {"is_active": "true"})

                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_children_reject_is_active_false_and_malformed_on_both_routes(self):
        for url in self.children_urls(self.india):
            for value in ("false", "False", "maybe", "1"):
                with self.subTest(url=url, value=value):
                    self.assert_errors(
                        self.client.get(url, {"is_active": value}),
                        [(errors.INVALID.code, "is_active")],
                    )

    def test_children_ignore_empty_filter_values_on_both_routes(self):
        params = {"location_type": "", "is_active": "", "parent_id": "", "parent_code": ""}
        for url in self.children_urls(self.india):
            with self.subTest(url=url):
                response = self.client.get(url, params)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                codes = {row["code"] for row in response.json()["results"]}
                self.assertEqual(codes, {"BR"})

    def test_children_report_every_invalid_field_at_once(self):
        for url in self.children_urls(self.india):
            with self.subTest(url=url):
                response = self.client.get(url, {"location_type": "tehsil", "is_active": "false"})

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(
                    {(e["code"], e.get("field")) for e in response.json()["errors"]},
                    {
                        (errors.INVALID_CHOICE.code, "location_type"),
                        (errors.INVALID.code, "is_active"),
                    },
                )

    def test_children_bad_params_are_400_whatever_the_parent(self):
        # Params are validated before the parent lookup, so an inactive or
        # unknown parent never turns a bad param into a 404.
        unknown_urls = [
            reverse("location-children", args=[uuid.uuid4()]),
            reverse("location-by-code-children", args=["NO_SUCH_CODE"]),
        ]
        cases = (
            ({"location_type": "tehsil"}, errors.INVALID_CHOICE.code, "location_type"),
            ({"is_active": "false"}, errors.INVALID.code, "is_active"),
            ({"is_active": "maybe"}, errors.INVALID.code, "is_active"),
            ({"parent_code": "BR"}, errors.INVALID.code, None),
        )
        for url in [*self.children_urls(self.goa), *unknown_urls]:
            for params, code, field in cases:
                with self.subTest(url=url, params=params):
                    self.assert_errors(self.client.get(url, params), [(code, field)])


class LocationAncestorsTests(LocationAPITestCase):
    """GET /locations/{id}/ancestors/ and /locations/code/{code}/ancestors/"""

    def test_ancestors_by_id_are_root_first(self):
        response = self.client.get(reverse("location-ancestors", args=[self.patna.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual([row["code"] for row in body["data"]], ["IN", "BR"])
        self.assert_meta(body)

    def test_ancestors_by_code_are_root_first(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual([row["code"] for row in body["data"]], ["IN", "BR"])
        self.assert_meta(body)

    def test_root_has_no_ancestors(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["IN"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["data"], [])
        self.assert_meta(body)

    def test_ancestors_of_unknown_code_returns_404(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["NOPE"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def ancestors_urls(self, location):
        """Return the by-id and by-code ancestors URLs of ``location``."""
        return [
            reverse("location-ancestors", args=[location.pk]),
            reverse("location-by-code-ancestors", args=[location.code]),
        ]

    def test_invalid_is_active_is_rejected_on_both_routes(self):
        for url in self.ancestors_urls(self.patna):
            for value in ("1", "ture", "yes"):
                with self.subTest(url=url, value=value):
                    response = self.client.get(url, {"is_active": value})

                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(
                        [
                            {"code": e["code"], "field": e.get("field")}
                            for e in response.json()["errors"]
                        ],
                        [{"code": errors.INVALID.code, "field": "is_active"}],
                    )

    def test_invalid_filters_are_rejected_on_both_routes(self):
        for url in self.ancestors_urls(self.patna):
            with self.subTest(url=url):
                self.assert_errors(
                    self.client.get(url, {"location_type": "tehsil"}),
                    [(errors.INVALID_CHOICE.code, "location_type")],
                )

    def test_is_active_true_needs_an_active_location_on_both_routes(self):
        for url in self.ancestors_urls(self.patna):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 200)
        for url in self.ancestors_urls(self.goa):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 404)

    def test_is_active_false_needs_an_inactive_location_on_both_routes(self):
        for url in self.ancestors_urls(self.patna):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"is_active": "false"}).status_code, 404)
        for url in self.ancestors_urls(self.goa):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"is_active": "false"}).status_code, 200)

    def test_is_active_true_needs_active_ancestors_on_both_routes(self):
        self.bihar.is_active = False
        self.bihar.save()

        for url in self.ancestors_urls(self.patna):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 404)
                self.assertEqual(self.client.get(url).status_code, 200)


class LocationRouteParityTests(LocationAPITestCase):
    """The id and code routes apply the same query filters to the location.

    The children routes are left out: their filters describe the children,
    not the location in the path (see LocationChildrenTests).
    """

    def route_pairs(self, location):
        """Return (name, id URL, code URL) for each route with an id and a code form."""
        return [
            (
                name,
                reverse(f"location-{id_name}", args=[location.pk]),
                reverse(f"location-by-code{code_suffix}", args=[location.code]),
            )
            for name, id_name, code_suffix in (
                ("detail", "detail", ""),
                ("ancestors", "ancestors", "-ancestors"),
            )
        ]

    def assert_same_status(self, location, params, expected):
        """Assert both forms of every route return ``expected`` for ``params``."""
        for name, id_url, code_url in self.route_pairs(location):
            for url in (id_url, code_url):
                with self.subTest(route=name, url=url, params=params):
                    self.assertEqual(self.client.get(url, params).status_code, expected)

    def test_matching_location_type_is_found(self):
        self.assert_same_status(self.patna, {"location_type": "district"}, 200)

    def test_other_location_type_is_not_found(self):
        self.assert_same_status(self.patna, {"location_type": "state"}, 404)

    def test_matching_parent_filters_are_found(self):
        self.assert_same_status(self.patna, {"parent_code": "BR"}, 200)
        self.assert_same_status(self.patna, {"parent_id": str(self.bihar.pk)}, 200)

    def test_other_parent_filters_are_not_found(self):
        self.assert_same_status(self.patna, {"parent_code": "IN"}, 404)
        self.assert_same_status(self.patna, {"parent_id": str(self.india.pk)}, 404)

    def test_is_active_filters_the_location(self):
        self.assert_same_status(self.patna, {"is_active": "true"}, 200)
        self.assert_same_status(self.patna, {"is_active": "false"}, 404)
        self.assert_same_status(self.goa, {"is_active": "false"}, 200)
        self.assert_same_status(self.goa, {"is_active": "true"}, 404)

    def test_empty_filter_values_are_ignored(self):
        self.assert_same_status(
            self.patna, {"location_type": "", "parent_code": "", "is_active": ""}, 200
        )

    def test_invalid_filters_are_rejected(self):
        for name, id_url, code_url in self.route_pairs(self.patna):
            for url in (id_url, code_url):
                with self.subTest(route=name, url=url):
                    self.assert_errors(
                        self.client.get(url, {"location_type": "tehsil", "is_active": "maybe"}),
                        [
                            (errors.INVALID_CHOICE.code, "location_type"),
                            (errors.INVALID.code, "is_active"),
                        ],
                    )

    def test_unknown_code_with_valid_filters_is_not_found(self):
        for suffix in ("", "-children", "-ancestors"):
            with self.subTest(suffix=suffix):
                url = reverse(f"location-by-code{suffix}", args=["NOPE"])
                self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 404)


class LocationFilterSchemaTests(APITestCase):
    """Every location route documents the query filters it validates and applies."""

    ROUTES = [
        "/api/v1/locations/",
        "/api/v1/locations/{id}/",
        "/api/v1/locations/{id}/ancestors/",
        "/api/v1/locations/code/{code}/",
        "/api/v1/locations/code/{code}/ancestors/",
    ]
    CHILDREN_ROUTES = [
        "/api/v1/locations/{id}/children/",
        "/api/v1/locations/code/{code}/children/",
    ]

    def setUp(self):
        self.schema = self.client.get(f"{reverse('api-schema')}?format=json").json()

    def test_every_route_documents_the_filters_and_their_errors(self):
        for path in self.ROUTES:
            with self.subTest(path=path):
                operation = self.schema["paths"][path]["get"]
                query = {p["name"] for p in operation["parameters"] if p["in"] == "query"}
                self.assertLessEqual(
                    {"location_type", "parent_id", "parent_code", "is_active"}, query
                )
                examples = operation["responses"]["400"]["content"]["application/json"]["examples"]
                self.assertLessEqual(
                    {
                        f"{errors.INVALID_CHOICE.code} (location_type)",
                        f"{errors.INVALID.code} (parent_id)",
                        f"{errors.INVALID.code} (parent_code)",
                        f"{errors.INVALID.code} (is_active)",
                    },
                    set(examples),
                )

    def test_children_routes_document_only_the_children_filters(self):
        for path in self.CHILDREN_ROUTES:
            with self.subTest(path=path):
                operation = self.schema["paths"][path]["get"]
                query = {p["name"] for p in operation["parameters"] if p["in"] == "query"}
                self.assertLessEqual({"location_type", "is_active"}, query)
                self.assertFalse({"parent_id", "parent_code"} & query)
                examples = operation["responses"]["400"]["content"]["application/json"]["examples"]
                self.assertLessEqual(
                    {
                        f"{errors.INVALID_CHOICE.code} (location_type)",
                        f"{errors.INVALID.code} (is_active)",
                    },
                    set(examples),
                )

    def test_ancestors_keep_their_is_active_description(self):
        for path in self.ROUTES:
            if not path.endswith("/ancestors/"):
                continue
            with self.subTest(path=path):
                (is_active,) = [
                    p
                    for p in self.schema["paths"][path]["get"]["parameters"]
                    if p["name"] == "is_active"
                ]
                self.assertIn("ancestors are active", is_active["description"])


class LocationWriteMethodTests(LocationAPITestCase):
    """v1 exposes no write endpoints."""

    def test_anonymous_post_is_forbidden(self):
        response = self.client.post(reverse("location-list"), {"code": "MH"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_post_is_not_allowed(self):
        self.client.force_authenticate(user=self._make_user())
        response = self.client.post(reverse("location-list"), {"code": "MH"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_session_cookie_post_is_not_allowed(self):
        user = self._make_user()
        self.assertTrue(self.client.login(mobile_number=user.mobile_number, password="test"))

        response = self.client.post(reverse("location-list"), {"code": "MH"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_authenticated_delete_is_not_allowed(self):
        self.client.force_authenticate(user=self._make_user())
        response = self.client.delete(reverse("location-detail", args=[self.patna.pk]))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def _make_user(self):
        """Create a user for permission-passing write attempts."""
        return User.objects.create_user(
            mobile_number="+919000000004",
            name="Editor",
            email="editor@example.com",
            password="test",
        )


class LocationURLPathTests(LocationAPITestCase):
    """The literal paths required by spec 0007 section 6 resolve correctly."""

    def test_spec_paths_resolve(self):
        base = "/api/v1/locations"
        paths = [
            f"{base}/",
            f"{base}/{self.patna.pk}/",
            f"{base}/code/PATNA/",
            f"{base}/{self.india.pk}/children/",
            f"{base}/code/IN/children/",
            f"{base}/{self.patna.pk}/ancestors/",
            f"{base}/code/PATNA/ancestors/",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_code_path_is_not_shadowed_by_detail_lookup(self):
        response = self.client.get("/api/v1/locations/code/BR/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.bihar.pk))
