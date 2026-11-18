"""Notification URL routing (spec 0031 §7)."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    # Declared before the router so it is never matched as a detail id.
    path(
        "notifications/subscribe/",
        views.NotificationSubscribeView.as_view(),
        name="notification-subscribe",
    ),
    path("", include(router.urls)),
]
