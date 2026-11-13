"""The hearings admin: read-only records, retire-only purposes (spec 0023 #11.10)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.cases.selectors import get_attendance_roll
from apps.hearings.enums import BulkMode, RescheduleReason
from apps.hearings.models import CourtCalendarEntry, HearingPurpose
from apps.hearings.services import courtroom, reschedule

from .factories import FRI, MON, TODAY, schedule

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    superuser = get_user_model().objects.create_superuser(
        mobile_number="+919000000001", name="admin", email="admin@example.com", password="x"
    )
    client.force_login(superuser)
    return client


def change_url(obj):
    meta = obj._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])


class TestReadOnlyRecords:
    def test_hearing_with_its_moves_and_attendance(self, admin_client, case):
        hearing = courtroom.start(hearing_id=schedule(case, TODAY).pk)
        entry = get_attendance_roll(case.pk)[0]
        courtroom.set_attendance(
            hearing_id=hearing.pk,
            marks=[
                {
                    "attendee_type": entry.type,
                    "participant_id": entry.participant_id,
                    "mark": "ABSENT",
                }
            ],
        )
        moved = schedule(case, MON)
        reschedule.reschedule(
            hearing_id=moved.pk, hearing_date=FRI, reason_code=RescheduleReason.NOT_REACHED
        )
        for url in (
            reverse("admin:hearings_hearing_changelist"),
            reverse("admin:hearings_hearingdatechange_changelist"),
            change_url(hearing),
            change_url(moved),
            change_url(moved.date_changes.get()),
        ):
            response = admin_client.get(url)
            assert response.status_code == 200, url
        page = admin_client.get(change_url(hearing)).content.decode()
        assert "Absent" in page
        assert "Save" not in page

    def test_hearing_cannot_be_added_edited_or_deleted(self, admin_client, case):
        hearing = schedule(case, MON)
        assert admin_client.get(reverse("admin:hearings_hearing_add")).status_code == 403
        assert admin_client.post(change_url(hearing), {"sequence": 9}).status_code == 403
        delete = reverse("admin:hearings_hearing_delete", args=[hearing.pk])
        assert admin_client.post(delete, {"post": "yes"}).status_code == 403
        hearing.refresh_from_db()
        assert hearing.sequence == 1

    def test_bulk_job_with_its_items(self, admin_client, courtroom, case):
        job = reschedule.preview_bulk(
            court_id=courtroom.pk,
            hearing_ids=[schedule(case, MON).pk],
            mode=BulkMode.TO_DATE,
            target_date=FRI,
            reason_code=RescheduleReason.PRESIDING_OFFICER_ON_LEAVE,
        ).job
        changelist = reverse("admin:hearings_bulkreschedulejob_changelist")
        assert admin_client.get(changelist).status_code == 200
        response = admin_client.get(change_url(job))
        assert response.status_code == 200
        assert "Pending" in response.content.decode()
        assert admin_client.post(change_url(job), {}).status_code == 403


class TestPurposes:
    def test_code_is_locked_once_created(self, admin_client):
        purpose = HearingPurpose.objects.get(code="APPEARANCE")
        response = admin_client.post(
            change_url(purpose),
            {"code": "RENAMED", "label": "Appearance", "sequence": 1, "is_active": "on"},
        )
        assert response.status_code == 302
        purpose.refresh_from_db()
        assert purpose.code == "APPEARANCE"

    def test_never_deleted(self, admin_client):
        purpose = HearingPurpose.objects.get(code="APPEARANCE")
        url = reverse("admin:hearings_hearingpurpose_delete", args=[purpose.pk])
        assert admin_client.post(url, {"post": "yes"}).status_code == 403
        assert HearingPurpose.objects.filter(pk=purpose.pk).exists()


class TestCalendarEntries:
    def test_capacity_error_shown_on_its_field(self, admin_client, courtroom):
        response = admin_client.post(
            reverse("admin:hearings_courtcalendarentry_add"),
            {
                "court": courtroom.pk,
                "date": MON.isoformat(),
                "entry_type": "HOLIDAY",
                "reason": "Onam",
                "capacity_override": 10,
            },
        )
        assert response.status_code == 200
        assert "capacity_override" in response.context["adminform"].form.errors
        assert not CourtCalendarEntry.objects.exists()
        listing = admin_client.get(reverse("admin:hearings_courtcalendarentry_changelist"))
        assert listing.status_code == 200
