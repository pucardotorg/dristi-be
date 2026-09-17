"""API URL routing."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.core.views import ApiVersionChangeLogViewSet, health_check

router = DefaultRouter()
router.register(
    r"api-version-changelogs",
    ApiVersionChangeLogViewSet,
    basename="api-version-changelog",
)

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("v1/", include("apps.users.urls")),
    path("v1/", include(router.urls)),
    path("v1/health/", health_check, name="health"),
]
