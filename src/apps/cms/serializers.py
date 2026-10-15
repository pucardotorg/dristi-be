"""CMS serializers (read-only for API v1)."""

from rest_framework import serializers

from .models import Page, PageCategory


class PageCategorySerializer(serializers.ModelSerializer):
    """Read-only representation of a page category."""

    class Meta:
        """Meta options."""

        model = PageCategory
        fields = ["id", "name", "slug"]
        read_only_fields = fields


class PageSerializer(serializers.ModelSerializer):
    """Read-only representation of a CMS page, with its categories nested."""

    categories = PageCategorySerializer(many=True, read_only=True)

    class Meta:
        """Meta options."""

        model = Page
        fields = [
            "id",
            "slug",
            "title",
            "sub_title",
            "main_image_url",
            "content_type",
            "content",
            "categories",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
