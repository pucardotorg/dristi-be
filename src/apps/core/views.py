"""Core app API views and viewsets."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.api import errors
from apps.api.schema import error_responses
from apps.api.viewsets import APIModelReadOnlyViewSet
from apps.api.viewsets.base import APIBaseViewSet, APIListMixin

from .models import ApiVersionChangeLog, PublicConfiguration, normalize_config_name, Language
from .serializers import (
    ApiVersionChangeLogSerializer,
    LanguageFilterSerializer,
    LanguageSerializer,
    PublicConfigurationSerializer,
)

# Dotted names (gateway.cdac.timeout) are allowed in both path parameters.
CONFIG_SET_URL_PATH = r"(?P<config_set>[^/]+)"
CONFIG_KEY_URL_PATH = CONFIG_SET_URL_PATH + r"/(?P<config_key>[^/]+)"


def index(request):
    """Root endpoint."""

    return HttpResponse("All is well")


@extend_schema(
    responses={
        200: inline_serializer(
            name="HealthCheckResponse",
            fields={"status": serializers.CharField()},
        )
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Lightweight liveness probe."""

    return Response({"status": "ok"})


@extend_schema_view(
    list=extend_schema(
        summary="List API version change logs",
        description="Return paginated API version changelog entries ordered by most recent.",
    ),
    retrieve=extend_schema(
        summary="Retrieve an API version change log",
        description="Return a single API version changelog entry by UUID.",
    ),
)
class ApiVersionChangeLogViewSet(APIModelReadOnlyViewSet):
    """Read-only API endpoints for API version change logs."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]
    database_model = ApiVersionChangeLog
    read_serializer_class = ApiVersionChangeLogSerializer

    def get_queryset(self):
        """Return changelog entries in model default ordering."""

        return super().get_queryset()


@extend_schema_view(
    list=extend_schema(
        summary="List supported languages",
        description=(
            "Return the active languages, ordered for display. Language-aware "
            "endpoints accept these codes in their `lang` query parameter."
        ),
        parameters=[LanguageFilterSerializer],
        responses=error_responses(
            errors.INVALID_CHOICE.example('"bogus" is not a valid choice.', field="supports"),
        ),
    ),
)
class LanguageViewSet(APIListMixin, APIBaseViewSet):
    """Public, read-only list of supported languages (spec 0030 section 4).

    List only: clients address languages by code, so no id-based ``retrieve``
    route is exposed. Languages are managed in admin.
    """

    permission_classes = [AllowAny]
    queryset = Language.objects.active()
    serializer_class = LanguageSerializer

    def get_queryset(self):
        """Return active languages, narrowed by the validated ``supports`` filter."""
        queryset = super().get_queryset()
        filters = LanguageFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        supports = filters.validated_data.get("supports")
        if supports:
            queryset = queryset.filter(supports__contains=[supports])
        return queryset


@extend_schema_view(
    by_set=extend_schema(
        summary="List public configuration in a set",
        description="Return the active entries of one set, ordered by key. An unknown set "
        "returns an empty page.",
    ),
    by_key=extend_schema(
        summary="Retrieve a public configuration entry",
        description="Return one active entry by its set and key. `config_value` is always "
        "a string; interpret it by `value_type`.",
    ),
)
class PublicConfigurationViewSet(APIBaseViewSet):
    """Public, read-only API over ``PublicConfiguration`` (spec 0034 section 3).

    Exactly two GET routes: a set listing and a set + key detail. There is no
    ``list`` or id-based ``retrieve``, no filtering or ordering parameters, and
    this view never reads ``Configuration``.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    filter_backends = []
    queryset = PublicConfiguration.objects.active()
    serializer_class = PublicConfigurationSerializer
    list_actions = {"by_set"}

    @action(detail=False, methods=["get"], url_path=CONFIG_SET_URL_PATH, url_name="by-set")
    def by_set(self, request, config_set=None):
        """Return a page of the active entries in one set."""
        entries = (
            self.get_queryset()
            .filter(config_set=normalize_config_name(config_set))
            .order_by("config_key")
        )
        page = self.paginate_queryset(entries)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @action(detail=False, methods=["get"], url_path=CONFIG_KEY_URL_PATH, url_name="by-key")
    def by_key(self, request, config_set=None, config_key=None):
        """Return one active entry matching both the set and the key."""
        entry = get_object_or_404(
            self.get_queryset(),
            config_set=normalize_config_name(config_set),
            config_key=normalize_config_name(config_key),
        )
        return Response(self.get_serializer(entry).data)
