"""Scrutiny, registration and filer-correction URL routing (spec 0024 #8)."""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("scrutiny", views.ScrutinyViewSet, basename="scrutiny")
router.register("registration", views.RegistrationViewSet, basename="registration")

urlpatterns = [
    *router.urls,
    # The filing side's routes sit under the case; apps.cases never imports scrutiny.
    path(
        "cases/<uuid:case_id>/corrections/",
        views.CorrectionsView.as_view(),
        name="case-corrections",
    ),
    path(
        "cases/<uuid:case_id>/corrections/submit/",
        views.CorrectionSubmitView.as_view(),
        name="case-corrections-submit",
    ),
    path(
        "cases/<uuid:case_id>/corrections/<uuid:flag_id>/explain/",
        views.CorrectionExplainView.as_view(),
        name="case-corrections-explain",
    ),
    path(
        "cases/<uuid:case_id>/scrutiny-history/",
        views.FilerHistoryView.as_view(),
        name="case-scrutiny-history",
    ),
]
