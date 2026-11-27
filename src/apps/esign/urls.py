"""eSign URL routing (spec 0015 #6).

Paths end with a slash, as every other API path does. The callback URL is
registered with the ESP and must match ``CDAC_ESIGN_RESPONSE_URL`` byte for
byte, slash included.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("esign/_esign/", views.ESignInitiateView.as_view(), name="esign-initiate"),
    path("esign/_signed/", views.ESignCallbackView.as_view(), name="esign-callback"),
    path("esign/methods/", views.ESignMethodsView.as_view(), name="esign-methods"),
    path(
        "esign/transactions/<uuid:transaction_id>/",
        views.ESignTransactionStatusView.as_view(),
        name="esign-transaction",
    ),
    path(
        "esign/transactions/<uuid:transaction_id>/_retry/",
        views.ESignRetryView.as_view(),
        name="esign-retry",
    ),
    path(
        "esign/transactions/<uuid:transaction_id>/_complete/",
        views.ClientSignatureCompleteView.as_view(),
        name="esign-complete",
    ),
]
