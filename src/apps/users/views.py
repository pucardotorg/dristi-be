"""Users app API views."""

from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.api.viewsets import APIModelReadOnlyViewSet

from .models import User
from .serializers import UserSerializer


@extend_schema_view(
    list=extend_schema(tags=["users"]),
    retrieve=extend_schema(tags=["users"]),
)
class UserViewSet(APIModelReadOnlyViewSet):
    """Read-only user API."""

    database_model = User
    read_serializer_class = UserSerializer
