"""URL routing for the requests app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"requests", views.RequestViewSet, basename="request")
router.register(r"request-types", views.RequestTypeViewSet, basename="request-type")
router.register(r"approvals", views.RequestApprovalViewSet, basename="request-approval")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "requests/<uuid:request_id>/documents/<uuid:document_id>/",
        views.RequestDocumentDownloadView.as_view(),
        name="request-document-download",
    ),
]
