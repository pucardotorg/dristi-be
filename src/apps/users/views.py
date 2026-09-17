"""Users app API views."""

from apps.api.viewsets import APIModelReadOnlyViewSet

from .models import User
from .serializers import UserSerializer


class UserViewSet(APIModelReadOnlyViewSet):
    """Read-only user API."""

    database_model = User
    read_serializer_class = UserSerializer
