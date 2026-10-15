"""CMS API views (read-only, public)."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.api.viewsets import APIModelReadOnlyViewSet

from .models import Page
from .serializers import PageSerializer

# Detail (id) routes only match UUIDs, so the ``slug/<slug>/`` route below is
# never mistaken for a page id.
UUID_REGEX = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
SLUG_URL_PATH = r"slug/(?P<slug>[-A-Za-z0-9]+)"


@extend_schema_view(
    list=extend_schema(tags=["CMS"]),
    retrieve=extend_schema(tags=["CMS"]),
    by_slug=extend_schema(tags=["CMS"]),
)
class PageViewSet(APIModelReadOnlyViewSet):
    """Public, read-only API for CMS pages (list + retrieve by slug)."""

    permission_classes = [AllowAny]
    queryset = Page.objects.prefetch_related("categories").all()
    serializer_class = PageSerializer
    lookup_value_regex = UUID_REGEX

    @action(detail=False, methods=["get"], url_path=SLUG_URL_PATH, url_name="by-slug")
    def by_slug(self, request, slug=None, *args, **kwargs):
        """Retrieve a single page by its unique slug."""
        page = get_object_or_404(Page.objects.prefetch_related("categories"), slug=slug)
        return Response(self.get_serializer(page).data)
