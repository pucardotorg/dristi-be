"""Organization URL routing."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"organizations", views.OrganizationViewSet, basename="organization")

urlpatterns = router.urls
