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
    # apps.api owns the schema, docs and health routes; each domain app is
    # mounted here so the whole API surface is visible in one file.
    path("api/", include("apps.api.urls")),
    path("api/v1/", include("apps.users.urls")),
    path("api/v1/", include("apps.locations.urls")),
    path("api/v1/", include("apps.organizations.urls")),
    path("api/v1/", include("apps.requests.urls")),
    path(
        "health/",
        HealthCheckView.as_view(checks=[DatabaseBackend, CacheBackend, RedisHealthCheck]),
    ),
]
