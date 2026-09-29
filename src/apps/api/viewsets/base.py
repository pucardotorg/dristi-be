"""Reusable DRF-native API viewset base classes and mixins."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import transaction
from django.http import Http404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.viewsets import GenericViewSet

from apps.api.serializers import AuditedModelSerializer
from apps.core.mixins import AuditUserMixin


def api_exception_handler(exc, context):
    """Default API exception handler wrapper.

    This currently delegates to DRF's default handler, while providing
    a project-level extension point for future normalization.
    """

    if isinstance(exc, Http404):
        # Keep DRF default 404 behavior.
        return drf_exception_handler(exc, context)
    return drf_exception_handler(exc, context)


class APIBaseViewSet(AuditUserMixin, GenericViewSet):
    """Base viewset with serializer selection + shared hooks.

    Inherits :class:`apps.core.mixins.AuditUserMixin` so that every write
    performed through the shared create/update pipelines stamps
    ``created_by`` / ``updated_by`` from the request user (spec 0002 section
    4.1). Models without those fields are left untouched.
    """

    database_model: ClassVar[type | None] = None
    lookup_field = "id"

    serializer_class = None
    read_serializer_class = None
    retrieve_serializer_class = None
    create_serializer_class = None
    update_serializer_class = None

    def get_exception_handler(self):
        """Return the exception handler used by this viewset."""

        return api_exception_handler

    def get_queryset(self):
        """Return queryset derived from database_model when queryset is unset."""

        if self.queryset is not None:
            queryset = self.queryset.all()
        elif self.database_model is not None:
            queryset = self.database_model.objects.all()
        else:
            raise ValueError(f"{self.__class__.__name__} must define queryset or database_model")
        return self._with_audit_users(queryset)

    def _with_audit_users(self, queryset):
        """Join the audit users in when the response will serialize them."""

        serializer_class = self.serializer_class or self.read_serializer_class
        if serializer_class is None or not issubclass(serializer_class, AuditedModelSerializer):
            return queryset
        return AuditedModelSerializer.with_audit_users(queryset)

    def get_read_serializer_class(self):
        """Serializer class for list responses."""

        return self.read_serializer_class or self.serializer_class

    def get_retrieve_serializer_class(self):
        """Serializer class for detail responses."""

        return self.retrieve_serializer_class or self.get_read_serializer_class()

    def get_create_serializer_class(self):
        """Serializer class for create requests."""

        return self.create_serializer_class or self.serializer_class

    def get_update_serializer_class(self):
        """Serializer class for update requests."""

        return self.update_serializer_class or self.get_create_serializer_class()

    def get_serializer_class(self):
        """Resolve serializer by action when possible."""

        if self.action == "list":
            serializer_class = self.get_read_serializer_class()
        elif self.action == "retrieve":
            serializer_class = self.get_retrieve_serializer_class()
        elif self.action == "create":
            serializer_class = self.get_create_serializer_class()
        elif self.action in {"update", "partial_update", "upsert"}:
            serializer_class = self.get_update_serializer_class()
        else:
            serializer_class = self.serializer_class or self.get_read_serializer_class()

        if serializer_class is None:
            raise ValueError(f"{self.__class__.__name__} must define serializer_class")
        return serializer_class

    def validate_data(self, serializer, model_obj=None):
        """Hook for cross-field or domain validation after serializer validation."""

    def authorize_list(self, request, queryset):
        """Hook to restrict list queryset by caller permissions."""

        return queryset


class APIRetrieveMixin:
    """Retrieve action with authorization hook."""

    def authorize_retrieve(self, model_instance):
        """Hook to authorize retrieve."""

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self.authorize_retrieve(instance)
        serializer = self.get_retrieve_serializer_class()(
            instance, context=self.get_serializer_context()
        )
        return Response(serializer.data)


class APIListMixin:
    """List action with authorization hook."""

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        queryset = self.authorize_list(request, queryset)

        page = self.paginate_queryset(queryset)
        serializer_class = self.get_read_serializer_class()

        if page is not None:
            serializer = serializer_class(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)

        serializer = serializer_class(queryset, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class APICreateMixin:
    """Create action with validation and authorization hooks."""

    def clean_create_data(self, request_data):
        """Hook to normalize incoming create payload."""

        return request_data

    def authorize_create(self, serializer):
        """Hook to authorize create using validated serializer."""

    def perform_create(self, serializer):
        """Persist create operation, stamping the audit fields."""

        return serializer.save(**self.get_audit_kwargs(serializer, creating=True))

    def _handle_create(self, request_data):
        serializer_class = self.get_create_serializer_class()
        serializer = serializer_class(
            data=self.clean_create_data(request_data),
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        self.validate_data(serializer, None)
        self.authorize_create(serializer)

        with transaction.atomic():
            return self.perform_create(serializer)

    def create(self, request, *args, **kwargs):
        instance = self._handle_create(request.data)
        response_serializer = self.get_retrieve_serializer_class()(
            instance,
            context=self.get_serializer_context(),
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class APIUpdateMixin:
    """Update actions with validation and authorization hooks."""

    def clean_update_data(self, request_data):
        """Hook to normalize incoming update payload."""

        return request_data

    def authorize_update(self, serializer, model_instance):
        """Hook to authorize update using validated serializer."""

    def perform_update(self, serializer):
        """Persist update operation, stamping ``updated_by``."""

        return serializer.save(**self.get_audit_kwargs(serializer, creating=False))

    def _handle_update(self, instance, request_data, partial=False):
        serializer_class = self.get_update_serializer_class()
        serializer = serializer_class(
            instance,
            data=self.clean_update_data(request_data),
            partial=partial,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        self.validate_data(serializer, instance)
        self.authorize_update(serializer, instance)

        with transaction.atomic():
            return self.perform_update(serializer)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        updated = self._handle_update(instance, request.data, partial=False)
        response_serializer = self.get_retrieve_serializer_class()(
            updated,
            context=self.get_serializer_context(),
        )
        return Response(response_serializer.data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        updated = self._handle_update(instance, request.data, partial=True)
        response_serializer = self.get_retrieve_serializer_class()(
            updated,
            context=self.get_serializer_context(),
        )
        return Response(response_serializer.data)


class APIDestroyMixin:
    """Destroy action with validation/authorization hooks."""

    def validate_destroy(self, instance):
        """Hook for domain-level pre-destroy validation."""

    def authorize_destroy(self, instance):
        """Hook to authorize destroy."""

    def perform_destroy(self, instance):
        """Delete behavior; override for soft-delete patterns."""

        instance.delete()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.validate_destroy(instance)
        self.authorize_destroy(instance)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class APIUpsertMixin:
    """Optional bulk upsert action using the shared create/update pipelines."""

    @action(detail=False, methods=["POST"])
    def upsert(self, request, *args, **kwargs):
        if not isinstance(request.data, dict):
            raise DRFValidationError("Invalid request data")

        datapoints = request.data.get("datapoints", [])
        if not isinstance(datapoints, list) or not datapoints:
            raise DRFValidationError("No datapoints provided")

        results: list[dict[str, Any]] = []
        had_error = False

        with transaction.atomic():
            for item in datapoints:
                if not isinstance(item, dict):
                    had_error = True
                    results.append({"error": "Each datapoint must be an object"})
                    continue

                lookup_value = item.get(self.lookup_field)
                if lookup_value is None and self.lookup_field != "id":
                    lookup_value = item.get("id")

                try:
                    if lookup_value is None:
                        instance = self._handle_create(item)
                    else:
                        instance = self.get_queryset().get(**{self.lookup_field: lookup_value})
                        instance = self._handle_update(instance, item, partial=False)

                    serializer = self.get_retrieve_serializer_class()(
                        instance,
                        context=self.get_serializer_context(),
                    )
                    results.append(serializer.data)
                except Exception as exc:  # noqa: BLE001
                    had_error = True
                    handled = self.get_exception_handler()(exc, {"view": self, "request": request})
                    if handled is not None and hasattr(handled, "data"):
                        results.append(handled.data)
                    else:
                        raise

            if had_error:
                transaction.set_rollback(True)
                return Response(results, status=status.HTTP_400_BAD_REQUEST)

        return Response(results, status=status.HTTP_200_OK)


class APIModelViewSet(
    APICreateMixin,
    APIRetrieveMixin,
    APIUpdateMixin,
    APIListMixin,
    APIDestroyMixin,
    APIBaseViewSet,
    APIUpsertMixin,
):
    """Full CRUD + upsert base viewset."""


class APIModelReadOnlyViewSet(
    APIRetrieveMixin,
    APIListMixin,
    APIBaseViewSet,
):
    """Read-only (list + retrieve) base viewset."""
