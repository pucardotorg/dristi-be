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
