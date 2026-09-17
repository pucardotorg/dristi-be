"""Locations API views."""

import uuid

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from apps.api.viewsets import APIModelReadOnlyViewSet

from .models import Location
from .serializers import LocationSerializer

UUID_REGEX = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CODE_URL_PATH = r"code/(?P<code>[^/.]+)"
BOOLEAN_VALUES = {"true": True, "false": False}


@extend_schema_view(
    list=extend_schema(tags=["locations"]),
    retrieve=extend_schema(tags=["locations"]),
    children=extend_schema(tags=["locations"]),
    ancestors=extend_schema(tags=["locations"]),
    by_code=extend_schema(tags=["locations"]),
    children_by_code=extend_schema(tags=["locations"]),
    ancestors_by_code=extend_schema(tags=["locations"]),
)
class LocationViewSet(APIModelReadOnlyViewSet):
    """Read-only location API with hierarchy lookups by id or code."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Location.objects.select_related("parent").all()
    serializer_class = LocationSerializer
    lookup_value_regex = UUID_REGEX

    def get_queryset(self):
        """Apply the location_type, parent and is_active query filters."""
        queryset = super().get_queryset()
        params = self.request.query_params

        location_type = params.get("location_type")
        if location_type is not None:
            if location_type not in Location.LocationType.values:
                raise ValidationError(
                    {
                        "location_type": (
                            f"Must be one of: {', '.join(Location.LocationType.values)}."
                        )
                    }
                )
            queryset = queryset.filter(location_type=location_type)

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

        is_active = params.get("is_active")
        if is_active is not None:
            if is_active.lower() not in BOOLEAN_VALUES:
                raise ValidationError({"is_active": "Must be 'true' or 'false'."})
            queryset = queryset.filter(is_active=BOOLEAN_VALUES[is_active.lower()])

        return queryset

    def _get_by_code(self, code):
        """Return the location with the given unique code or raise 404."""
        return get_object_or_404(Location.objects.select_related("parent"), code=code)

    def _children_response(self, location):
        """Return a paginated response of the location's direct children."""
        children = location.children.select_related("parent").order_by("code")
        page = self.paginate_queryset(children)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(children, many=True).data)

    def _ancestors_response(self, location):
        """Return the ancestor chain from root to immediate parent."""
        return Response(self.get_serializer(location.get_ancestors(), many=True).data)

    @action(detail=True, methods=["get"], url_path="children", url_name="children")
    def children(self, request, *args, **kwargs):
        """List the direct children of a location identified by id."""
        return self._children_response(self.get_object())

    @action(detail=True, methods=["get"], url_path="ancestors", url_name="ancestors")
    def ancestors(self, request, *args, **kwargs):
        """List the ancestors of a location identified by id."""
        return self._ancestors_response(self.get_object())

    @action(detail=False, methods=["get"], url_path=CODE_URL_PATH, url_name="by-code")
    def by_code(self, request, code=None, *args, **kwargs):
        """Retrieve a location by its unique code."""
        return Response(self.get_serializer(self._get_by_code(code)).data)

    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/children",
        url_name="by-code-children",
    )
    def children_by_code(self, request, code=None, *args, **kwargs):
        """List the direct children of a location identified by code."""
        return self._children_response(self._get_by_code(code))

    @action(
        detail=False,
        methods=["get"],
        url_path=f"{CODE_URL_PATH}/ancestors",
        url_name="by-code-ancestors",
    )
    def ancestors_by_code(self, request, code=None, *args, **kwargs):
        """List the ancestors of a location identified by code."""
        return self._ancestors_response(self._get_by_code(code))
