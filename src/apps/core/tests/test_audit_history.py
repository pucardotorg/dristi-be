"""Tests for BaseAuditableModel history tracking via django-simple-history.

See spec/0004-simple-audit-history.md ("Testing strategy") for the scenarios these
tests are based on. The spec's examples use an illustrative `Document` model; here
they are adapted to the real auditable models defined in `apps.core.models`:
`AdditionalAttribute` (inherits `BaseAuditableModel` directly) and
`ApiVersionChangeLog` (inherits `BaseExtendableModel, BaseAuditableModel`).

Note: the installed django-simple-history version implements
`HistoryRequestMiddleware` as a function-based middleware (it wraps
`get_response`) rather than exposing `process_request`/`process_response`
hooks, so `_run_with_history_user` below drives it the way it's actually meant
to be used instead of the older class-based API shown in the spec.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.utils import timezone
from simple_history.middleware import HistoryRequestMiddleware
from simple_history.utils import (
    bulk_create_with_history,
    bulk_update_with_history,
    update_change_reason,
)

from apps.core.models import AdditionalAttribute, ApiVersionChangeLog

User = get_user_model()


def _run_with_history_user(user, callback):
    """Run `callback` inside a request context so `history_user` is captured."""
    request = RequestFactory().post("/")
    request.user = user
    middleware = HistoryRequestMiddleware(lambda req: callback())
    return middleware(request)


@pytest.mark.django_db
class TestApiVersionChangeLogHistory:
    """History behavior for ApiVersionChangeLog (BaseExtendableModel + BaseAuditableModel)."""

    def test_history_record_created_on_create(self):
        ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Original")

        assert ApiVersionChangeLog.history.count() == 1
        latest = ApiVersionChangeLog.history.latest()
        assert latest.history_type == "+"
        assert latest.version == "1.0.0"

    def test_history_record_created_on_save(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Original")
        changelog.change_log = "Updated"
        changelog.save()

        assert ApiVersionChangeLog.history.count() == 2
        latest = ApiVersionChangeLog.history.latest()
        assert latest.change_log == "Updated"
        assert latest.history_type == "~"

    def test_history_records_deleted_instance(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="To delete")
        changelog.delete()

        assert ApiVersionChangeLog.history.latest().history_type == "-"

    def test_history_user_set_via_middleware(self):
        user = User.objects.create_user(
            username="auditor", email="auditor@example.com", password="pw12345"
        )
        changelog = _run_with_history_user(
            user,
            lambda: ApiVersionChangeLog.objects.create(version="1.0.0", change_log="By user"),
        )

        assert changelog.history.latest().history_user == user

    def test_history_user_none_outside_request_context(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="No request")

        assert changelog.history.latest().history_user is None

    def test_change_reason_recorded(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Reasoned")
        update_change_reason(changelog, "Manually annotated for audit")

        assert changelog.history.latest().history_change_reason == "Manually annotated for audit"

    def test_bulk_create_with_history(self):
        changelogs = [
            ApiVersionChangeLog(version=f"1.{i}.0", change_log=f"Batch {i}") for i in range(3)
        ]
        bulk_create_with_history(changelogs, ApiVersionChangeLog)

        assert ApiVersionChangeLog.history.filter(history_type="+").count() == 3

    def test_bulk_update_with_history(self):
        changelogs = [
            ApiVersionChangeLog.objects.create(version=f"2.{i}.0", change_log="Original")
            for i in range(3)
        ]
        for changelog in changelogs:
            changelog.change_log = "Bulk updated"
        bulk_update_with_history(changelogs, ApiVersionChangeLog, ["change_log"])

        assert ApiVersionChangeLog.history.filter(history_type="~").count() == 3

    def test_as_of_returns_snapshot_before_change(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Original")
        before_update = timezone.now()
        changelog.change_log = "Updated"
        changelog.save()

        snapshot = changelog.history.as_of(before_update)
        assert snapshot.change_log == "Original"

    def test_filter_history_by_type_and_recent_date(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Original")

        recent_creations = ApiVersionChangeLog.history.filter(
            history_type="+", history_date__gte=timezone.now() - timedelta(days=1)
        )
        assert changelog.id in recent_creations.values_list("id", flat=True)

    def test_diff_against(self):
        changelog = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Original")
        changelog.change_log = "Updated"
        changelog.save()

        old, new = changelog.history.order_by("history_id")
        diff = new.diff_against(old)

        assert "change_log" in {change.field for change in diff.changes}


@pytest.mark.django_db
class TestAdditionalAttributeHistory:
    """History behavior for AdditionalAttribute (inherits BaseAuditableModel directly)."""

    @pytest.fixture
    def content_type(self):
        return ContentType.objects.get_for_model(ApiVersionChangeLog)

    def test_history_record_created_on_create(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
        )

        assert AdditionalAttribute.history.count() == 1
        assert AdditionalAttribute.history.latest().history_type == "+"

    def test_history_record_created_on_save(self, content_type):
        attr = AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
        )
        attr.is_nullable = False
        attr.default_value = 0
        attr.save()

        assert AdditionalAttribute.history.count() == 2
        latest = AdditionalAttribute.history.latest()
        assert latest.is_nullable is False
        assert latest.history_type == "~"

    def test_history_records_deleted_instance(self, content_type):
        attr = AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
        )
        attr.delete()

        assert AdditionalAttribute.history.latest().history_type == "-"

    def test_history_user_set_via_middleware(self, content_type):
        user = User.objects.create_user(
            username="attr_auditor", email="attr_auditor@example.com", password="pw12345"
        )
        attr = _run_with_history_user(
            user,
            lambda: AdditionalAttribute.objects.create(
                content_type=content_type,
                name="tracked",
                data_type="character",
                is_nullable=True,
            ),
        )

        assert attr.history.latest().history_user == user