"""Locations API views."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.api import errors
from apps.api.schema import error_responses
from apps.api.viewsets import APIModelReadOnlyViewSet
from apps.core.fields import StrictBooleanField

from .models import Location
from .serializers import LocationFilterSerializer, LocationSerializer

UUID_REGEX = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CODE_URL_PATH = r"code/(?P<code>[^/.]+)"
IS_ACTIVE_MESSAGE = StrictBooleanField.default_error_messages["invalid"]
# The pincode pre-fill asks for an all-active chain (spec 0007 section 7).
ANCESTORS_IS_ACTIVE = OpenApiParameter(
    "is_active",
    str,
    enum=["true", "false"],
    description=(
        "'true': not found unless the location and all its ancestors are active. "
        "'false': not found unless the location itself is inactive."
    ),
)
# Every route runs LocationFilterSerializer through get_queryset(), so each one
# accepts these query parameters and can return these errors.
FILTER_ERRORS = error_responses(
    errors.INVALID_CHOICE.example('"XX" is not a valid choice.', field="location_type"),
    errors.INVALID.example("Must be a valid UUID.", field="parent_id"),
    errors.INVALID.example("No location exists with code 'XX'.", field="parent_code"),
    errors.INVALID.example(IS_ACTIVE_MESSAGE, field="is_active"),
    errors.INVALID.example("parent_id and parent_code are mutually exclusive."),
)
FILTERED_SCHEMA = extend_schema(parameters=[LocationFilterSerializer], responses=FILTER_ERRORS)
# ANCESTORS_IS_ACTIVE comes after the serializer, so its description wins.
ANCESTORS_SCHEMA = extend_schema(
    parameters=[LocationFilterSerializer, ANCESTORS_IS_ACTIVE], responses=FILTER_ERRORS
)


@extend_schema_view(list=FILTERED_SCHEMA, retrieve=FILTERED_SCHEMA)
class LocationViewSet(APIModelReadOnlyViewSet):
    """Read-only location API with hierarchy lookups by id or code."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Location.objects.select_related("parent").all()
    serializer_class = LocationSerializer
    lookup_value_regex = UUID_REGEX
    list_actions = {"children", "children_by_code"}
    # Ancestor chains are short and returned whole; documented as plain lists.
    unpaginated_actions = {"ancestors", "ancestors_by_code"}

    def get_filter_params(self):
        """Return the validated query filters, raising a 400 on a bad value."""
        if not hasattr(self, "_filter_params"):
            filters = LocationFilterSerializer(data=self.request.query_params)
            filters.is_valid(raise_exception=True)
            self._filter_params = filters.validated_data
        return self._filter_params

    def get_queryset(self):
        """Apply the location_type, parent and is_active query filters.

        They apply to every route built on this queryset, detail and code
        lookups included, so the id and code routes answer a query alike.
        """
        queryset = super().get_queryset()
        params = self.get_filter_params()

        if "location_type" in params:
            queryset = queryset.filter(location_type=params["location_type"])
        if "parent_id" in params:
            queryset = queryset.filter(parent_id=params["parent_id"])
        if "parent_code" in params:
            queryset = queryset.filter(parent__code=params["parent_code"])
        if "is_active" in params:
            queryset = queryset.filter(is_active=params["is_active"])

        return queryset

    def _get_by_code(self, code):
        """Return the location with this code that passes the query filters, or 404."""
        return get_object_or_404(self.get_queryset(), code=code)

    def _children_response(self, location):
        """Return a paginated response of the location's direct children."""
        children = location.children.select_related("parent").order_by("code")
        page = self.paginate_queryset(children)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(children, many=True).data)

    def _ancestors_response(self, location):
        """Return the ancestor chain from root to immediate parent.

        With ``is_active=true`` a chain with any inactive link, the location
        itself included, is not found: address forms pre-fill from a pincode's
        ancestors, and a deactivated pincode or district must not pre-fill.
        The queryset has already applied every filter to the location itself,
        so ``is_active=false`` never reaches here with an active location.
        """
        ancestors = location.get_ancestors()
        if self.get_filter_params().get("is_active") and not all(
            link.is_active for link in ancestors
        ):
            raise NotFound("No active location with an active ancestor chain was found.")
        return Response(self.get_serializer(ancestors, many=True).data)

    @FILTERED_SCHEMA
    @action(detail=True, methods=["get"], url_path="children", url_name="children")
    def children(self, request, *args, **kwargs):
        """List the direct children of a location identified by id."""
        return self._children_response(self.get_object())

    @ANCESTORS_SCHEMA
    @action(detail=True, methods=["get"], url_path="ancestors", url_name="ancestors")
    def ancestors(self, request, *args, **kwargs):
        """List the ancestors of a location identified by id."""
        return self._ancestors_response(self.get_object())

    @FILTERED_SCHEMA
    @action(detail=False, methods=["get"], url_path=CODE_URL_PATH, url_name="by-code")
    def by_code(self, request, code=None, *args, **kwargs):
        """Retrieve a location by its unique code."""
        return Response(self.get_serializer(self._get_by_code(code)).data)

    @FILTERED_SCHEMA
    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/children",
        url_name="by-code-children",
    )
    def children_by_code(self, request, code=None, *args, **kwargs):
        """List the direct children of a location identified by code."""
        return self._children_response(self._get_by_code(code))

    @ANCESTORS_SCHEMA
    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/ancestors",
        url_name="by-code-ancestors",
    )
    def ancestors_by_code(self, request, code=None, *args, **kwargs):
        """List the ancestors of a location identified by code."""
        return self._ancestors_response(self._get_by_code(code))
