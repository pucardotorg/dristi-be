"""Scrutiny URL routing (spec 0024 #8)."""

from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("scrutiny", views.ScrutinyViewSet, basename="scrutiny")

urlpatterns = router.urls
