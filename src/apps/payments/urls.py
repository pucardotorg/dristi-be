"""Payments URL routing (spec 0017 #12).

Mounted at ``/api/v1/``; this module owns the ``payments/`` segment. The
callback path carries no trailing slash because it is registered with the
provider and must match byte for byte.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

URL_PREFIX = "payments/"

router = SimpleRouter()
router.register(r"demands", views.DemandViewSet, basename="payments-demand")
router.register(r"payments", views.PaymentViewSet, basename="payments-payment")
router.register(r"batches", views.BatchViewSet, basename="payments-batch")

app_urlpatterns = [
    path("providers/", views.ProviderListView.as_view(), name="payments-providers"),
    # Collection desk (spec 0032 #9.2, #9.3); fixed segments before the lookup.
    path("collections/", views.CollectionListView.as_view(), name="payments-collections"),
    path(
        "collections/methods/",
        views.CollectionMethodsView.as_view(),
        name="payments-collection-methods",
    ),
    path(
        "collections/register/",
        views.CollectionRegisterView.as_view(),
        name="payments-collection-register",
    ),
    path(
        "collections/<str:provider>/<str:reference>/",
        views.CollectionDetailView.as_view(),
        name="payments-collection-detail",
    ),
    path(
        "collections/<str:provider>/<str:reference>/confirm/",
        views.CollectionConfirmView.as_view(),
        name="payments-collection-confirm",
    ),
    path(
        "collections/<str:provider>/<str:reference>/cancel/",
        views.CollectionCancelView.as_view(),
        name="payments-collection-cancel",
    ),
    path(
        "providers/options/",
        views.ProviderOptionsView.as_view(),
        name="payments-provider-options",
    ),
    path(
        "providers/<str:provider>/_callback",
        views.ProviderCallbackView.as_view(),
        name="payments-provider-callback",
    ),
    *router.urls,
]

urlpatterns = [
    path(URL_PREFIX, include(app_urlpatterns)),
]
