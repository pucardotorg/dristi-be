"""GET /api/v1/court-roles/me/ (spec 0029 #9.2, #12 "API")."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.api.errors import NOT_AUTHENTICATED
from apps.organizations import services
from apps.organizations.tests.court_factories import (
    TwoCourtsMixin,
    assign,
    make_role,
    make_user,
)

from . import court_actions as actions

URL = reverse("court-roles-me")


class MyCourtRolesTests(TwoCourtsMixin, APITestCase):
    """The caller's courts, roles and effective actions."""

    def setUp(self):
        self.make_courts()
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def get(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("meta", response.json())
        return response.json()["establishments"]

    def test_anonymous_is_refused(self):
        self.client.force_authenticate(None)
        response = self.client.get(URL)
        # Session authentication sends no challenge header, so DRF answers 403.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["errors"][0]["code"], NOT_AUTHENTICATED.code)

    def test_no_court_access_is_an_empty_list(self):
        self.assertEqual(self.get(), [])

    def test_establishment_actions_only(self):
        assign(self.user, self.est_a, make_role("SCRUTINY", [actions.FORWARD, actions.FLAG]))
        self.assertEqual(
            self.get(),
            [
                {
                    "id": str(self.est_a.pk),
                    "name": "Establishment A",
                    "actions": ["testing.flag", "testing.forward"],
                    "courtrooms": [],
                }
            ],
        )

    def test_courtroom_role_only(self):
        assign(self.user, self.room_a1, make_role("TYPIST", [actions.EDIT], name="Typist"))
        services.assign_courtroom(self.user, self.room_a2, actor=None)
        (establishment,) = self.get()
        self.assertEqual(establishment["actions"], [])
        self.assertEqual(
            establishment["courtrooms"],
            [
                {
                    "id": str(self.room_a1.pk),
                    "name": "Courtroom A1",
                    "roles": [{"code": "TYPIST", "name": "Typist"}],
                    "actions": ["testing.edit"],
                },
                {"id": str(self.room_a2.pk), "name": "Courtroom A2", "roles": [], "actions": []},
            ],
        )

    def test_mixed_level_role_and_scoped_actions(self):
        role = make_role(
            "MAGISTRATE",
            [
                actions.SIGN,
                actions.REGISTER,
                (actions.PROCESS_SIGN, {"process_types": ["WARRANT"]}),
                (actions.PROCESS_SIGN, {"process_types": ["SUMMONS"], "channels": ["RPAD"]}),
            ],
            name="Magistrate",
        )
        assign(self.user, self.room_a1, role)
        (establishment,) = self.get()
        # The establishment action held through the courtroom role is listed on the establishment.
        self.assertEqual(establishment["actions"], ["testing.register"])
        (courtroom,) = establishment["courtrooms"]
        self.assertEqual(courtroom["roles"], [{"code": "MAGISTRATE", "name": "Magistrate"}])
        self.assertEqual(courtroom["actions"][1], "testing.sign")
        scoped = courtroom["actions"][0]
        self.assertEqual(scoped["action"], "testing.process_sign")
        self.assertCountEqual(
            scoped["scopes"],
            [{"process_types": ["WARRANT"]}, {"process_types": ["SUMMONS"], "channels": ["RPAD"]}],
        )

    def test_unregistered_account_may_call_it(self):
        """Any signed-in account may call it, not only those past the citizen wizard."""
        self.assertFalse(self.user.is_registration_complete)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_200_OK)
