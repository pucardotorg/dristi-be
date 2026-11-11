"""Django URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from health_check.views import HealthCheckView
from redis import Redis

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
    path("api/v1/", include("apps.dristi_requests.urls")),
    path("api/v1/", include("apps.pdf.urls")),
    path("api/v1/", include("apps.cases.urls")),
    path("api/v1/", include("apps.scrutiny.urls")),
    path("api/v1/", include("apps.esign.urls")),
    path("api/v1/", include("apps.cms.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path(
        "health/",
        HealthCheckView.as_view(
            # Import-string names (3.21+, and the same in 4.x). Bare classes
            # make 3.24 raise TypeError on every request.
            checks=[
                "health_check.Database",
                "health_check.Cache",
                # Redis is the Dramatiq broker. test.py's stub broker has no
                # url, hence .get().
                (
                    "health_check.contrib.redis.Redis",
                    {
                        "client": Redis.from_url(
                            settings.DRAMATIQ_BROKER["OPTIONS"].get(
                                "url", "redis://localhost:6379/2"
                            )
                        )
                    },
                ),
            ]
        ),
    ),
]

# local.py installs the toolbar middleware; without its URLs every HTML page
# fails with "'djdt' is not a registered namespace".
if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]

# Standard error shape for /api/ requests that never reach DRF — spec 0000 section 9.5.
handler400 = "apps.api.errors.handler400"
handler403 = "apps.api.errors.handler403"
handler404 = "apps.api.errors.handler404"
handler500 = "apps.api.errors.handler500"
