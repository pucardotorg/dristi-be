"""URL routing for the dristi requests app.

Mounted at ``/api/v1/dristi-requests/``. Requests themselves live at the
prefix root, so the more specific ``approvals/`` and ``request-types/``
prefixes are registered first, and detail routes only match UUIDs.

``SimpleRouter`` rather than ``DefaultRouter``: the latter serves a browsable
API root at ``""``, which is where the request list lives here.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register(r"approvals", views.RequestApprovalViewSet, basename="request-approval")
router.register(r"request-types", views.RequestTypeViewSet, basename="request-type")
router.register(r"", views.RequestViewSet, basename="request")

urlpatterns = [
    *router.urls,
    path(
        "<uuid:request_id>/documents/<uuid:document_id>/",
        views.RequestDocumentDownloadView.as_view(),
        name="request-document-download",
    ),
]
