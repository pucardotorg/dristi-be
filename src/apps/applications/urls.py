"""Applications URL routing (spec 0033 #15).

Owns ``/applications/…`` and the ``/cases/{case_id}/…`` application routes.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

UUID = views.UUID_PATTERN

router = SimpleRouter()
router.register("applications", views.ApplicationViewSet, basename="application")
router.register(
    rf"cases/(?P<case_id>{UUID})/applications",
    views.CaseApplicationsViewSet,
    basename="case-application",
)

urlpatterns = [
    path(
        "cases/<uuid:case_id>/application-types/",
        views.ApplicationTypesView.as_view(),
        name="case-application-types",
    ),
    path(
        "cases/<uuid:case_id>/application-types/<str:code>/form/",
        views.ApplicationFormView.as_view(),
        name="case-application-form",
    ),
    path(
        "applications/<uuid:pk>/documents/<str:document_id>/",
        views.ApplicationDocumentView.as_view(),
        name="application-document",
    ),
    *router.urls,
]
