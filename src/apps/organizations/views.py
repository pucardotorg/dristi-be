"""Organization views."""

from django.shortcuts import get_object_or_404
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Organization
from .serializers import OrganizationFilterSerializer, OrganizationSerializer


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only organization API, looked up by id."""

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

        is_active = params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        return queryset

    @action(detail=True, methods=["get"])
    def children(self, request, id=None):
        """List direct children of this organization."""
        organization = self.get_object()
        children = organization.children.select_related("parent").all()
        serializer = self.get_serializer(children, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def ancestors(self, request, id=None):
        """List the ancestor chain from root to immediate parent."""
        organization = self.get_object()
        serializer = self.get_serializer(organization.get_ancestors(), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def jurisdictions(self, request, id=None):
        """List jurisdiction locations for this organization.

        TODO(0007-location): depends on the location app (spec/0007-location.md),
        which is not implemented yet. Returns an empty list until then.
        """
        self.get_object()
        return Response([])


class OrganizationByCodeMixin:
    """Look up the organization named by the `code` URL kwarg, or 404."""

    def get_organization(self):
        """Return the organization matching the `code` URL kwarg."""
        return get_object_or_404(Organization, code=self.kwargs["code"])


class OrganizationCodeDetailView(OrganizationByCodeMixin, generics.RetrieveAPIView):
    """Retrieve an organization by its unique code."""

    serializer_class = OrganizationSerializer

    def get_object(self):
        """Return the organization matching the `code` URL kwarg."""
        return self.get_organization()


class OrganizationCodeChildrenView(OrganizationByCodeMixin, generics.ListAPIView):
    """List direct children of the organization identified by code."""

    serializer_class = OrganizationSerializer
    pagination_class = None

    def get_queryset(self):
        """Return direct children of the organization matching the `code` kwarg."""
        return self.get_organization().children.select_related("parent").all()


class OrganizationCodeAncestorsView(OrganizationByCodeMixin, generics.GenericAPIView):
    """List the ancestor chain of the organization identified by code."""

    serializer_class = OrganizationSerializer

    def get(self, request, code):
        """Return the ancestor chain from root to immediate parent."""
        serializer = self.get_serializer(self.get_organization().get_ancestors(), many=True)
        return Response(serializer.data)


class OrganizationCodeJurisdictionsView(OrganizationByCodeMixin, generics.GenericAPIView):
    """List jurisdiction locations of the organization identified by code.

    TODO(0007-location): depends on the location app (spec/0007-location.md),
    which is not implemented yet. Returns an empty list until then.
    """

    serializer_class = OrganizationSerializer

    def get(self, request, code):
        """Validate the organization exists and return an empty jurisdiction list."""
        self.get_organization()
        return Response([])
