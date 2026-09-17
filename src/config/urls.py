"""Django URL configuration."""

from django.contrib import admin
from django.urls import include, path
from health_check.cache.backends import CacheBackend
from health_check.contrib.redis.backends import RedisHealthCheck
from health_check.db.backends import DatabaseBackend
from health_check.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.api.urls")),
    path("api/v1/", include("apps.locations.urls")),
    path(
        "health/",
        HealthCheckView.as_view(checks=[DatabaseBackend, CacheBackend, RedisHealthCheck]),
    ),
]
