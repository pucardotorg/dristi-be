"""Address URL routing."""

from django.urls import path

from . import views

urlpatterns = [
    path("pincodes/<str:pincode>/", views.PincodeLookupView.as_view(), name="pincode-lookup"),
]
