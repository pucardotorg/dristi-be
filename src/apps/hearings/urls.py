"""Hearings URL routing (spec 0023 #10.1).

Owns ``/cases/{case_id}/hearings/`` and ``/courts/{court_id}/...`` too, so
``apps.cases`` and ``apps.organizations`` stay unaware of hearings.
"""

from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
# Before "hearings": its own routes, never a hearing id.
router.register(
    "hearings/bulk-reschedule", views.BulkRescheduleViewSet, basename="hearing-bulk-reschedule"
)
router.register("hearings", views.HearingViewSet, basename="hearing")
router.register("hearing-purposes", views.HearingPurposeViewSet, basename="hearing-purpose")
router.register("courts", views.CourtHearingsViewSet, basename="court-hearings")
router.register(
    rf"cases/(?P<case_id>{views.UUID_PATTERN})/hearings",
    views.CaseHearingsViewSet,
    basename="case-hearings",
)

urlpatterns = router.urls
