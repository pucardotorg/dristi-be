"""Routes for registration and login (spec 0005 section 4)."""

from django.urls import path

from . import views

urlpatterns = [
    path("auth/otp/request", views.OTPRequestView.as_view(), name="otp-request"),
    path("users", views.UserCreateView.as_view(), name="user-create"),
    path("sessions", views.SessionView.as_view(), name="session"),
    path("litigants", views.LitigantRegistrationView.as_view(), name="litigant-create"),
    path("advocates", views.AdvocateRegistrationView.as_view(), name="advocate-create"),
    path("clerks", views.ClerkRegistrationView.as_view(), name="clerk-create"),
]
