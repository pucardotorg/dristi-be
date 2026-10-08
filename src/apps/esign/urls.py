"""eSign URL routing (spec 0015 #6).

The paths carry no trailing slash because the callback URL is registered with
the ESP and must match byte for byte.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("esign/_esign", views.ESignInitiateView.as_view(), name="esign-initiate"),
    path("esign/_signed", views.ESignCallbackView.as_view(), name="esign-callback"),
    path(
        "esign/transactions/<uuid:transaction_id>",
        views.ESignTransactionStatusView.as_view(),
        name="esign-transaction",
    ),
    path(
        "esign/transactions/<uuid:transaction_id>/_retry",
        views.ESignRetryView.as_view(),
        name="esign-retry",
    ),
]
