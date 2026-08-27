"""API URL routing."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"users", views.UserViewSet, basename="user")

urlpatterns = [
    path("v1/", include(router.urls)),
    path("v1/health/", views.health_check, name="health"),
    path("v1/tasks/demo/", views.demo_task, name="demo-task"),
]
