"""Locations API views."""

import uuid

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.api import errors
from apps.api.schema import error_responses
from apps.api.viewsets import APIModelReadOnlyViewSet

from .models import Location
from .serializers import LocationSerializer

UUID_REGEX = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CODE_URL_PATH = r"code/(?P<code>[^/.]+)"
BOOLEAN_VALUES = {"true": True, "false": False}
IS_ACTIVE_MESSAGE = "Must be 'true' or 'false'."
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
ANCESTORS_SCHEMA = extend_schema(
    parameters=[ANCESTORS_IS_ACTIVE],
    responses=error_responses(errors.INVALID.example(IS_ACTIVE_MESSAGE, field="is_active")),
)
UNSUPPORTED_CHILDREN_FILTERS = (
    "Only location_type filters the children; the parent is identified by the URL path "
    "and inactive children are never listed."
)
CHILDREN_SCHEMA = extend_schema(
    parameters=[
        OpenApiParameter(
            "location_type",
            str,
            enum=Location.LocationType.values,
            description="Only children of this type; inactive children are never listed.",
        ),
    ],
    responses=error_responses(
        errors.INVALID_CHOICE.example(
            f"Must be one of: {', '.join(Location.LocationType.values)}.",
            field="location_type",
        ),
        errors.INVALID.example(UNSUPPORTED_CHILDREN_FILTERS),
    ),
)


def parse_is_active(params):
    """Return the ``is_active`` query parameter as a bool, or None when absent.

    Raises a 400 for any other value, so a typo is never silently ignored.
    """
    value = params.get("is_active")
    if value is None:
        return None
    if value.lower() not in BOOLEAN_VALUES:
        raise ValidationError({"is_active": IS_ACTIVE_MESSAGE})
    return BOOLEAN_VALUES[value.lower()]


@extend_schema_view(
    # Query parameters are validated in get_queryset(), outside any serializer.
    list=extend_schema(
        responses=error_responses(
            errors.INVALID_CHOICE.example(
                f"Must be one of: {', '.join(Location.LocationType.values)}.",
                field="location_type",
            ),
            errors.INVALID.example("Must be a valid UUID.", field="parent_id"),
            errors.INVALID.example("No location exists with code 'XX'.", field="parent_code"),
            errors.INVALID.example(IS_ACTIVE_MESSAGE, field="is_active"),
            errors.INVALID.example(
                "parent_id and parent_code are mutually exclusive; supply only one."
            ),
        )
    ),
)
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

    def get_queryset(self):
        """Apply the location_type, parent and is_active query filters."""
        queryset = super().get_queryset()
        if getattr(self, "action", None) in self.list_actions:
            # The children actions identify the parent in the URL path, so
            # the query filters describe the children and are applied in
            # _children_response(), not on the parent's lookup.
            return queryset
        queryset = self._apply_location_type_filter(queryset)
        params = self.request.query_params

        parent_id = params.get("parent_id")
        parent_code = params.get("parent_code")
        if parent_id is not None and parent_code is not None:
            raise ValidationError(
                "parent_id and parent_code are mutually exclusive; supply only one."
            )
        if parent_id is not None:
            try:
                parent_uuid = uuid.UUID(parent_id)
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValidationError({"parent_id": "Must be a valid UUID."}) from exc
            queryset = queryset.filter(parent_id=parent_uuid)
        if parent_code is not None:
            parent = Location.objects.filter(code=parent_code).first()
            if parent is None:
                raise ValidationError(
                    {"parent_code": f"No location exists with code {parent_code!r}."}
                )
            queryset = queryset.filter(parent_id=parent.pk)

        is_active = parse_is_active(params)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        return queryset

    def _location_type_param(self):
        """Return the validated location_type query param, or None when absent."""
        location_type = self.request.query_params.get("location_type")
        if location_type is not None and location_type not in Location.LocationType.values:
            raise errors.INVALID_CHOICE.validation_error(
                {"location_type": f"Must be one of: {', '.join(Location.LocationType.values)}."}
            )
        return location_type

    def _apply_location_type_filter(self, queryset):
        """Filter a location collection by the location_type query param."""
        location_type = self._location_type_param()
        if location_type is not None:
            queryset = queryset.filter(location_type=location_type)
        return queryset

    def _get_by_code(self, code):
        """Return the location with the given unique code or raise 404."""
        return get_object_or_404(Location.objects.select_related("parent"), code=code)

    def _validate_children_params(self):
        """Reject bad children query params before the parent is looked up.

        ``location_type`` is the only filter; the parent and ``is_active``
        filters are rejected rather than ignored. Validating first means a bad
        param is always a 400, whether the parent is active, inactive or unknown.
        """
        params = self.request.query_params
        if any(param in params for param in ("parent_id", "parent_code", "is_active")):
            raise ValidationError(UNSUPPORTED_CHILDREN_FILTERS)
        self._location_type_param()

    def _children_response(self, location):
        """Return a paginated response of the location's active direct children.

        Call ``_validate_children_params()`` before looking ``location`` up.
        An inactive parent is not found and inactive children are never listed.
        """
        if not location.is_active:
            raise NotFound("No active location matches the given query.")
        children = self._apply_location_type_filter(
            location.children.filter(is_active=True).select_related("parent")
        ).order_by("code")
        page = self.paginate_queryset(children)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(children, many=True).data)

    def _ancestors_response(self, location):
        """Return the ancestor chain from root to immediate parent.

        With ``is_active=true`` a chain with any inactive link, the location
        itself included, is not found: address forms pre-fill from a pincode's
        ancestors, and a deactivated pincode or district must not pre-fill.
        With ``is_active=false`` an active location is not found, as the id
        route's queryset filter already does. Any other value is a 400.
        """
        is_active = parse_is_active(self.request.query_params)
        ancestors = location.get_ancestors()
        if is_active and not all(link.is_active for link in [location, *ancestors]):
            raise NotFound("No active location with an active ancestor chain was found.")
        if is_active is False and location.is_active:
            raise NotFound("No inactive location with this code was found.")
        return Response(self.get_serializer(ancestors, many=True).data)

    @CHILDREN_SCHEMA
    @action(detail=True, methods=["get"], url_path="children", url_name="children")
    def children(self, request, *args, **kwargs):
        """List the direct children of a location identified by id."""
        self._validate_children_params()
        return self._children_response(self.get_object())

    @ANCESTORS_SCHEMA
    @action(detail=True, methods=["get"], url_path="ancestors", url_name="ancestors")
    def ancestors(self, request, *args, **kwargs):
        """List the ancestors of a location identified by id."""
        return self._ancestors_response(self.get_object())

    @action(detail=False, methods=["get"], url_path=CODE_URL_PATH, url_name="by-code")
    def by_code(self, request, code=None, *args, **kwargs):
        """Retrieve a location by its unique code."""
        return Response(self.get_serializer(self._get_by_code(code)).data)

    @CHILDREN_SCHEMA
    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/children",
        url_name="by-code-children",
    )
    def children_by_code(self, request, code=None, *args, **kwargs):
        """List the direct children of a location identified by code."""
        self._validate_children_params()
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
