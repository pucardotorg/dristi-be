"""Organization URL routing."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"", views.OrganizationViewSet, basename="organization")

urlpatterns = [
    path(
        "code/<str:code>/",
        views.OrganizationCodeDetailView.as_view(),
        name="organization-code-detail",
    ),
    path(
        "code/<str:code>/children/",
        views.OrganizationCodeChildrenView.as_view(),
        name="organization-code-children",
    ),
    path(
        "code/<str:code>/ancestors/",
        views.OrganizationCodeAncestorsView.as_view(),
        name="organization-code-ancestors",
    ),
    path(
        "code/<str:code>/jurisdictions/",
        views.OrganizationCodeJurisdictionsView.as_view(),
        name="organization-code-jurisdictions",
    ),
    path("", include(router.urls)),
]
