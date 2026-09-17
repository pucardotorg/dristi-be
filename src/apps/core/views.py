"""Core app API views and viewsets."""

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.api.viewsets import APIModelReadOnlyViewSet

from .models import ApiVersionChangeLog
from .serializers import ApiVersionChangeLogSerializer


def index(request):
    """Root endpoint."""

    return HttpResponse("All is well")


@extend_schema(
    tags=["core"],
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
        tags=["core"],
    ),
    retrieve=extend_schema(
        summary="Retrieve an API version change log",
        description="Return a single API version changelog entry by UUID.",
        tags=["core"],
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
