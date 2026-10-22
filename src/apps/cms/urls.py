"""CMS URL routing."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"cms/pages", views.PageViewSet, basename="cms-page")

urlpatterns = router.urls
