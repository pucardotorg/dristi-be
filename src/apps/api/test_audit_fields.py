"""API-level tests for the created_by / updated_by audit fields.

A minimal, test-only viewset over ``ApiVersionChangeLog`` is used so the audit
behaviour of :class:`apps.core.mixins.AuditUserMixin` and
:class:`apps.api.serializers.AuditedModelSerializer` can be exercised without
adding a write API to the production URL configuration.
"""

from django.test import override_settings
from django.urls import include, path, reverse
from rest_framework import status, viewsets
from rest_framework.routers import DefaultRouter
from rest_framework.test import APITestCase

from apps.api.serializers import AuditedModelSerializer
from apps.api.viewsets import APIModelViewSet
from apps.core.mixins import AuditUserMixin
from apps.core.models import ApiVersionChangeLog
from apps.users.models import RegistrationStatus, User


class ChangeLogSerializer(AuditedModelSerializer):
    """Test-only serializer for the change-log model."""

    class Meta:
        """Meta options."""

        model = ApiVersionChangeLog
        fields = ["id", "version", "change_log", "created_by", "updated_by"]


class ChangeLogViewSet(AuditUserMixin, viewsets.ModelViewSet):
    """Test-only writable viewset."""

    queryset = ApiVersionChangeLog.objects.all()
    serializer_class = ChangeLogSerializer


class WritableChangeLogSerializer(AuditedModelSerializer):
    """Test-only writable serializer for the shared base viewset."""

    class Meta:
        """Meta options."""

        model = ApiVersionChangeLog
        fields = ["id", "version", "change_log", "created_by", "updated_by"]


class BaseChangeLogViewSet(APIModelViewSet):
    """Test-only viewset on the project's shared CRUD base class."""

    queryset = ApiVersionChangeLog.objects.all()
    serializer_class = WritableChangeLogSerializer


router = DefaultRouter()
router.register(r"changelogs", ChangeLogViewSet, basename="test-changelog")
router.register(r"base-changelogs", BaseChangeLogViewSet, basename="test-base-changelog")

urlpatterns = [path("test-api/", include(router.urls))]


@override_settings(ROOT_URLCONF=__name__)
class AuditFieldAPITests(APITestCase):
    """Audit population and protection through the API."""

    def setUp(self):
        # The project's default permissions require a finished registration,
        # so these accounts are created past the wizard: this suite is about
        # audit fields, not the registration gate.
        self.user = User.objects.create_user(
            mobile_number="+919000000004",
            name="creator",
            email="creator@example.com",
            password="test",
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.other_user = User.objects.create_user(
            mobile_number="+919000000005",
            name="other",
            email="other@example.com",
            password="test",
            registration_status=RegistrationStatus.COMPLETE,
        )

    def test_create_sets_both_audit_fields_to_request_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-changelog-list"),
            {"version": "1.0.0", "change_log": "Initial release."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = ApiVersionChangeLog.objects.get(pk=response.json()["id"])
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.user)

    def test_update_keeps_created_by_and_sets_updated_by(self):
        entry = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Initial release.",
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            reverse("test-changelog-detail", args=[entry.pk]),
            {"change_log": "Amended."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry.refresh_from_db()
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.other_user)

    def test_client_cannot_set_audit_fields_on_create(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-changelog-list"),
            {
                "version": "1.0.0",
                "change_log": "Initial release.",
                "created_by": str(self.other_user.pk),
                "updated_by": str(self.other_user.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = ApiVersionChangeLog.objects.get(pk=response.json()["id"])
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.user)

    def test_client_cannot_set_audit_fields_on_update(self):
        entry = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Initial release.",
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            reverse("test-changelog-detail", args=[entry.pk]),
            {"created_by": str(self.other_user.pk), "updated_by": str(self.user.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry.refresh_from_db()
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.other_user)

    def test_audit_fields_are_serialized_read_only(self):
        entry = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Initial release.",
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("test-changelog-detail", args=[entry.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["created_by"]["id"], str(self.user.pk))
        self.assertEqual(payload["updated_by"]["id"], str(self.user.pk))

        serializer = ChangeLogSerializer()
        self.assertTrue(serializer.fields["created_by"].read_only)
        self.assertTrue(serializer.fields["updated_by"].read_only)

    def test_null_audit_fields_are_serialized_as_null(self):
        entry = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="System import.")
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("test-changelog-detail", args=[entry.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["created_by"])
        self.assertIsNone(response.json()["updated_by"])


@override_settings(ROOT_URLCONF=__name__)
class SharedBaseViewSetAuditTests(APITestCase):
    """The shared CRUD base viewsets must stamp the audit fields themselves.

    ``APIModelViewSet`` is the documented default foundation for write APIs,
    so audit population has to come with it; relying on each app to remember
    ``AuditUserMixin`` is how the fields end up permanently NULL.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            mobile_number="+919000000006",
            name="base-creator",
            email="base-creator@example.com",
            password="test",
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.other_user = User.objects.create_user(
            mobile_number="+919000000007",
            name="base-editor",
            email="base-editor@example.com",
            password="test",
            registration_status=RegistrationStatus.COMPLETE,
        )

    def test_create_through_base_viewset_stamps_both_fields(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-base-changelog-list"),
            {"version": "2.0.0", "change_log": "Created through the base viewset."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = ApiVersionChangeLog.objects.get(pk=response.json()["id"])
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.user)

    def test_update_through_base_viewset_keeps_created_by(self):
        entry = ApiVersionChangeLog.objects.create(
            version="2.0.0",
            change_log="Entry.",
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            reverse("test-base-changelog-detail", args=[entry.pk]),
            {"change_log": "Amended."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry.refresh_from_db()
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.other_user)

    def test_audit_representation_exposes_no_contact_details(self):
        entry = ApiVersionChangeLog.objects.create(
            version="2.2.0",
            change_log="Entry.",
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("test-base-changelog-detail", args=[entry.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        created_by = response.json()["created_by"]
        # Attribution needs an id and a display name; it does not need the
        # actor's mobile number or email handed to every reader.
        self.assertEqual(set(created_by), {"id", "name"})
        self.assertEqual(created_by["id"], str(self.user.pk))
        self.assertEqual(created_by["name"], self.user.name)

    def test_list_does_not_query_per_row_for_audit_users(self):
        for index in range(5):
            ApiVersionChangeLog.objects.create(
                version=f"3.{index}.0",
                change_log="Entry.",
                created_by=self.user,
                updated_by=self.other_user,
            )
        self.client.force_authenticate(user=self.user)
        url = reverse("test-base-changelog-list")

        # The pagination count and the page itself. Both audit users are
        # joined into the page query instead of costing two queries per row.
        with self.assertNumQueries(2):
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 5)

    def test_client_cannot_forge_audit_fields_through_base_viewset(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse("test-base-changelog-list"),
            {
                "version": "2.1.0",
                "change_log": "Forged.",
                "created_by": str(self.other_user.pk),
                "updated_by": str(self.other_user.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = ApiVersionChangeLog.objects.get(pk=response.json()["id"])
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.updated_by, self.user)
