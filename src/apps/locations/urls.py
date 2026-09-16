"""Locations URL routing."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"locations", views.LocationViewSet, basename="location")

urlpatterns = router.urls
