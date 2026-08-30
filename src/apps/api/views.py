"""API views."""

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.tasks import send_welcome_email
from apps.users.models import User

from .serializers import UserSerializer


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only user API."""

    queryset = User.objects.all()
    serializer_class = UserSerializer


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Lightweight liveness probe."""
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([AllowAny])
def version(request):
    """Return the Git commit SHA the image was built from."""
    return Response({"git_version": getattr(settings, "GIT_COMMIT_SHA", "unknown")})


@api_view(["POST"])
def demo_task(request):
    """Enqueue a background task and return its message ID."""
    email = request.data.get("email")
    if not email:
        return Response(
            {"error": "email is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    message = send_welcome_email.send(email)
    return Response(
        {"status": "enqueued", "message_id": message.message_id},
        status=status.HTTP_202_ACCEPTED,
    )
