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
from apps.core.mixins import AuditUserMixin
from apps.core.models import ApiVersionChangeLog
from apps.users.models import User


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


router = DefaultRouter()
router.register(r"changelogs", ChangeLogViewSet, basename="test-changelog")

urlpatterns = [path("test-api/", include(router.urls))]


@override_settings(ROOT_URLCONF=__name__)
class AuditFieldAPITests(APITestCase):
    """Audit population and protection through the API."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="creator@example.com", username="creator", password="test"
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", username="other", password="test"
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
        response = self.client.get(reverse("test-changelog-detail", args=[entry.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["created_by"]["id"], self.user.pk)
        self.assertEqual(payload["updated_by"]["id"], self.user.pk)

        serializer = ChangeLogSerializer()
        self.assertTrue(serializer.fields["created_by"].read_only)
        self.assertTrue(serializer.fields["updated_by"].read_only)

    def test_null_audit_fields_are_serialized_as_null(self):
        entry = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="System import.")
        response = self.client.get(reverse("test-changelog-detail", args=[entry.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["created_by"])
        self.assertIsNone(response.json()["updated_by"])
