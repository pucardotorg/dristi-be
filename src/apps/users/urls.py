"""Routes for registration and login (spec 0005 section 4).

Paths carry a trailing slash to match DRF's `DefaultRouter`, which the rest of
the project's apps are routed through.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("auth/otp/request/", views.OTPRequestView.as_view(), name="otp-request"),
    path(
        "auth/password-reset/verify/",
        views.PasswordResetVerifyView.as_view(),
        name="password-reset-verify",
    ),
    path("auth/password-reset/", views.PasswordResetView.as_view(), name="password-reset"),
    path("users/", views.UserCreateView.as_view(), name="user-create"),
    path("users/me/", views.CurrentUserView.as_view(), name="user-me"),
    path("users/me/terms/", views.TermsView.as_view(), name="user-terms"),
    path("sessions/", views.SessionView.as_view(), name="session"),
    path("litigants/", views.LitigantRegistrationView.as_view(), name="litigant-create"),
    path(
        "power-of-attorneys/",
        views.PowerOfAttorneyRegistrationView.as_view(),
        name="power-of-attorney-create",
    ),
    path("advocates/", views.AdvocateRegistrationView.as_view(), name="advocate-create"),
    path("clerks/", views.ClerkRegistrationView.as_view(), name="clerk-create"),
    path(
        "registrations/current/",
        views.CurrentRegistrationView.as_view(),
        name="registration-current",
    ),
    path(
        "registrations/current/resubmit/",
        views.RegistrationResubmitView.as_view(),
        name="registration-resubmit",
    ),
]
