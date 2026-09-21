"""Django URL configuration."""

from django.contrib import admin
from django.urls import include, path
from health_check.cache.backends import CacheBackend
from health_check.contrib.redis.backends import RedisHealthCheck
from health_check.db.backends import DatabaseBackend
from health_check.views import HealthCheckView

from apps.core.views import index

urlpatterns = [
    path("", index),
    path("admin/", admin.site.urls),
    # apps.users.urls is mounted inside apps.api.urls, alongside the other
    # v1 routes and the schema endpoints.
    path("api/", include("apps.api.urls")),
    path("api/v1/", include("apps.locations.urls")),
    path("api/v1/", include("apps.organizations.urls")),
    path(
        "health/",
        HealthCheckView.as_view(checks=[DatabaseBackend, CacheBackend, RedisHealthCheck]),
    ),
]
