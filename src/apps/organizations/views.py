"""Organization views."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.api.viewsets import APIModelReadOnlyViewSet
from apps.locations.serializers import LocationSerializer

from .models import Organization
from .serializers import OrganizationFilterSerializer, OrganizationSerializer

CODE_URL_PATH = r"code/(?P<code>[^/.]+)"


@extend_schema_view(
    list=extend_schema(tags=["organizations"]),
    retrieve=extend_schema(tags=["organizations"]),
    children=extend_schema(tags=["organizations"]),
    ancestors=extend_schema(tags=["organizations"]),
    jurisdictions=extend_schema(tags=["organizations"]),
    by_code=extend_schema(tags=["organizations"]),
    children_by_code=extend_schema(tags=["organizations"]),
    ancestors_by_code=extend_schema(tags=["organizations"]),
    jurisdictions_by_code=extend_schema(tags=["organizations"]),
)
class OrganizationViewSet(APIModelReadOnlyViewSet):
    """Read-only organization API with hierarchy and jurisdiction lookups by id or code."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Organization.objects.select_related("parent").all()
    serializer_class = OrganizationSerializer
    lookup_field = "id"

    def get_queryset(self):
        """Apply list-endpoint filters only when listing, not on detail lookups."""
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = self._filter_queryset(queryset)
        return queryset

    def _filter_queryset(self, queryset):
        """Validate query params via OrganizationFilterSerializer and apply them."""
        filters = OrganizationFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        params = filters.validated_data

        organization_type = params.get("organization_type")
        if organization_type:
            queryset = queryset.filter(organization_type=organization_type)

        parent_id = params.get("parent_id")
        parent_code = params.get("parent_code")
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)
        elif parent_code:
            queryset = queryset.filter(parent__code=parent_code)

        jurisdiction_id = params.get("jurisdiction_id")
        jurisdiction_code = params.get("jurisdiction_code")
        if jurisdiction_id:
            queryset = queryset.filter(jurisdictions__id=jurisdiction_id)
        elif jurisdiction_code:
            queryset = queryset.filter(jurisdictions__code=jurisdiction_code)

        is_active = params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        return queryset

    def _get_by_code(self, code):
        """Return the organization with the given unique code or raise 404."""
        return get_object_or_404(Organization.objects.select_related("parent"), code=code)

    def _children_response(self, organization):
        """Return a paginated response of the organization's direct children."""
        children = organization.children.select_related("parent").all()
        page = self.paginate_queryset(children)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(children, many=True).data)

    def _ancestors_response(self, organization):
        """Return the ancestor chain from root to immediate parent."""
        return Response(self.get_serializer(organization.get_ancestors(), many=True).data)

    def _jurisdictions_response(self, organization):
        """Return a paginated response of the organization's jurisdiction locations."""
        jurisdictions = organization.jurisdictions.all()
        page = self.paginate_queryset(jurisdictions)
        if page is not None:
            return self.get_paginated_response(LocationSerializer(page, many=True).data)
        return Response(LocationSerializer(jurisdictions, many=True).data)

    @action(detail=True, methods=["get"], url_path="children", url_name="children")
    def children(self, request, *args, **kwargs):
        """List the direct children of an organization identified by id."""
        return self._children_response(self.get_object())

    @action(detail=True, methods=["get"], url_path="ancestors", url_name="ancestors")
    def ancestors(self, request, *args, **kwargs):
        """List the ancestors of an organization identified by id."""
        return self._ancestors_response(self.get_object())

    @action(detail=True, methods=["get"], url_path="jurisdictions", url_name="jurisdictions")
    def jurisdictions(self, request, *args, **kwargs):
        """List the jurisdiction locations of an organization identified by id."""
        return self._jurisdictions_response(self.get_object())

    @action(detail=False, methods=["get"], url_path=CODE_URL_PATH, url_name="by-code")
    def by_code(self, request, code=None, *args, **kwargs):
        """Retrieve an organization by its unique code."""
        return Response(self.get_serializer(self._get_by_code(code)).data)

    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/children",
        url_name="by-code-children",
    )
    def children_by_code(self, request, code=None, *args, **kwargs):
        """List the direct children of an organization identified by code."""
        return self._children_response(self._get_by_code(code))

    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/ancestors",
        url_name="by-code-ancestors",
    )
    def ancestors_by_code(self, request, code=None, *args, **kwargs):
        """List the ancestors of an organization identified by code."""
        return self._ancestors_response(self._get_by_code(code))

    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/jurisdictions",
        url_name="by-code-jurisdictions",
    )
    def jurisdictions_by_code(self, request, code=None, *args, **kwargs):
        """List the jurisdiction locations of an organization identified by code."""
        return self._jurisdictions_response(self._get_by_code(code))
