"""URL routing for the dristi requests app.

Mounted at ``/api/v1/`` like the other domain apps; this module owns the
``dristi-requests/`` segment so the app's whole public surface is defined in
one place.

Requests themselves live at the ``dristi-requests/`` root, so the more
specific ``approvals/`` and ``request-types/`` prefixes are registered first,
and detail routes only match UUIDs.

``SimpleRouter`` rather than ``DefaultRouter``: the latter serves a browsable
API root at ``""``, which is where the request list lives here.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

URL_PREFIX = "dristi-requests/"

router = SimpleRouter()
router.register(r"approvals", views.RequestApprovalViewSet, basename="request-approval")
router.register(r"request-types", views.RequestTypeViewSet, basename="request-type")
router.register(r"", views.RequestViewSet, basename="request")

app_urlpatterns = [
    *router.urls,
    path(
        "<uuid:request_id>/documents/<uuid:document_id>/",
        views.RequestDocumentDownloadView.as_view(),
        name="request-document-download",
    ),
]

urlpatterns = [
    path(URL_PREFIX, include(app_urlpatterns)),
]
