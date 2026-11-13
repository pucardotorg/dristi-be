"""Core app API views and viewsets."""

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.api import errors
from apps.api.schema import error_responses
from apps.api.viewsets import APIModelReadOnlyViewSet
from apps.api.viewsets.base import APIBaseViewSet, APIListMixin

from .models import ApiVersionChangeLog, Language
from .serializers import (
    ApiVersionChangeLogSerializer,
    LanguageFilterSerializer,
    LanguageSerializer,
)


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
