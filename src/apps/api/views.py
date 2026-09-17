"""API views."""

from apps.users.models import User

from .serializers import UserSerializer
from .viewsets import APIModelReadOnlyViewSet


class UserViewSet(APIModelReadOnlyViewSet):
    """Read-only user API."""

    database_model = User
    read_serializer_class = UserSerializer



