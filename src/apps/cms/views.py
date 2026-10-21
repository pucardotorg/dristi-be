"""CMS API views (read-only, public)."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.api.viewsets.base import APIBaseViewSet, APIListMixin

from .models import Page
from .serializers import PageSerializer

SLUG_URL_PATH = r"slug/(?P<slug>[-A-Za-z0-9]+)"


@extend_schema_view(
    list=extend_schema(tags=["CMS"]),
    by_slug=extend_schema(tags=["CMS"]),
)
class PageViewSet(APIListMixin, APIBaseViewSet):
    """Public, read-only API for CMS pages.

    Spec 0018 section 5 defines exactly two endpoints: list and fetch-by-slug.
    The base is deliberately ``APIListMixin + APIBaseViewSet`` (not the
    read-only viewset) so no id-based ``retrieve`` route is exposed.
    """

    permission_classes = [AllowAny]
    queryset = Page.objects.prefetch_related("categories").all()
    serializer_class = PageSerializer

    @action(detail=False, methods=["get"], url_path=SLUG_URL_PATH, url_name="by-slug")
    def by_slug(self, request, slug=None, *args, **kwargs):
        """Fetch a single page by its unique slug."""
        page = get_object_or_404(Page.objects.prefetch_related("categories"), slug=slug)
        return Response(self.get_serializer(page).data)
