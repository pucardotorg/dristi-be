"""Users app serializers."""

from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for the custom user model."""

    class Meta:
        """Meta options."""

        model = User
        fields = ["id", "email", "username", "is_active", "date_joined"]
        read_only_fields = ["id", "date_joined"]
