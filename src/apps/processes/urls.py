"""Processes URL routing (spec 0028 #11).

Owns ``/cases/{case_id}/processes/`` too, so ``apps.cases`` stays unaware of
processes. Police stations are read from the locations API
(``location_type=police_station``).
"""

from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("processes", views.ProcessViewSet, basename="process")
router.register("process-types", views.ProcessTypeViewSet, basename="process-type")
router.register(
    "non-delivery-reasons", views.NonDeliveryReasonViewSet, basename="non-delivery-reason"
)
router.register(
    rf"cases/(?P<case_id>{views.UUID_PATTERN})/processes",
    views.CaseProcessesViewSet,
    basename="case-processes",
)

urlpatterns = router.urls
