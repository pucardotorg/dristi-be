"""Organization URL routing."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"organizations", views.OrganizationViewSet, basename="organization")

urlpatterns = [
    path("court-roles/me/", views.MyCourtRolesView.as_view(), name="court-roles-me"),
    *router.urls,
]
