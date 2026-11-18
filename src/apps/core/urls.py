"""Core URL routing."""

from rest_framework.routers import SimpleRouter

from . import views

# Only the viewset's two GET actions are routed: no list of every set and no
# id-based detail (spec 0034 section 3.5).
router = SimpleRouter()
router.register(
    r"public-configuration", views.PublicConfigurationViewSet, basename="public-configuration"
)

urlpatterns = router.urls
