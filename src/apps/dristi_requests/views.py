"""API views for the generic request and approval workflow."""

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Request, RequestApproval, RequestDocument, RequestType
from .serializers import (
    DecisionSerializer,
    GenericRequestCreateSerializer,
    RequestApprovalDetailSerializer,
    RequestApprovalSerializer,
    RequestDetailSerializer,
    RequestSerializer,
    RequestTypeSerializer,
)


@extend_schema_view(
    list=extend_schema(tags=["dristi_requests"]),
    retrieve=extend_schema(tags=["dristi_requests"]),
)
class RequestTypeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """List available request types and their schemas."""

    permission_classes = [IsAuthenticated]
    serializer_class = RequestTypeSerializer
    queryset = RequestType.objects.active().prefetch_related("approval_steps")


@extend_schema_view(
    list=extend_schema(tags=["dristi_requests"]),
    retrieve=extend_schema(tags=["dristi_requests"], responses=RequestDetailSerializer),
    create=extend_schema(tags=["dristi_requests"], responses=RequestDetailSerializer),
    approvals=extend_schema(
        tags=["dristi_requests"], responses=RequestApprovalSerializer(many=True)
    ),
    resubmit=extend_schema(
        tags=["dristi_requests"], request=None, responses=RequestDetailSerializer
    ),
    cancel=extend_schema(tags=["dristi_requests"], request=None, responses=RequestDetailSerializer),
)
class RequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Submitter-side request API."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return the caller's own requests (staff see every request)."""
        queryset = (
            Request.objects.select_related("request_type", "requester")
            .prefetch_related("documents", "approvals__approver")
            .all()
        )
        user = getattr(self.request, "user", None)
        if user is None or not user.is_authenticated:
            return queryset.none()
        if user.is_staff or user.is_superuser:
            return queryset
        return queryset.filter(requester=user)

    def get_serializer_class(self):
        """Return the serializer matching the current action."""
        if self.action == "create":
            return GenericRequestCreateSerializer
        if self.action == "retrieve":
            return RequestDetailSerializer
        if self.action == "approvals":
            return RequestApprovalSerializer
        return RequestSerializer

    def create(self, request, *args, **kwargs):
        """Create and submit a request of any type (multipart)."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        output = RequestDetailSerializer(instance, context=self.get_serializer_context())
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def approvals(self, request, pk=None):
        """Return the approval trail for a request."""
        instance = self.get_object()
        queryset = instance.approvals.select_related("approver").all()
        serializer = RequestApprovalSerializer(
            queryset, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def resubmit(self, request, pk=None):
        """Resubmit a rejected request, starting a new approval round."""
        instance = self._get_own_request()
        services.resubmit(instance, actor=request.user)
        instance.refresh_from_db()
        serializer = RequestDetailSerializer(instance, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a draft, pending or rejected request."""
        instance = self._get_own_request()
        services.cancel(instance, actor=request.user)
        instance.refresh_from_db()
        serializer = RequestDetailSerializer(instance, context=self.get_serializer_context())
        return Response(serializer.data)

    def _get_own_request(self):
        """Return the request being acted on, restricted to its requester."""
        instance = self.get_object()
        user = self.request.user
        if instance.requester_id != user.pk and not (user.is_staff or user.is_superuser):
            raise Http404
        return instance


@extend_schema_view(
    list=extend_schema(
        tags=["dristi_requests"],
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                many=True,
                enum=[choice.value for choice in RequestApproval.Status],
                description="Filter by approval status; repeat for multiple values. "
                "Defaults to pending.",
            )
        ],
    ),
    retrieve=extend_schema(tags=["dristi_requests"], responses=RequestApprovalDetailSerializer),
    decide=extend_schema(
        tags=["dristi_requests"],
        request=DecisionSerializer,
        responses=RequestApprovalDetailSerializer,
    ),
)
class RequestApprovalViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Approver-side API: pending queue, decision history, and decide()."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return approvals assigned to the caller, filtered by status."""
        user = getattr(self.request, "user", None)
        base = RequestApproval.objects.select_related(
            "request", "request__request_type", "request__requester", "approver"
        ).prefetch_related("request__documents")
        if user is None or not user.is_authenticated:
            return base.none()

        queryset = base.filter(approver=user)
        statuses = self.request.query_params.getlist("status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)
        elif self.action == "list":
            queryset = queryset.filter(status=RequestApproval.Status.PENDING)
        return queryset

    def get_serializer_class(self):
        """Return the serializer matching the current action."""
        if self.action == "retrieve":
            return RequestApprovalDetailSerializer
        return RequestApprovalSerializer

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        """Approve or reject the approval assigned to the caller."""
        approval = self.get_object()
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        approval = services.decide(
            approval,
            serializer.validated_data["decision"],
            actor=request.user,
            comments=serializer.validated_data.get("comments", ""),
        )
        approval.refresh_from_db()
        output = RequestApprovalDetailSerializer(approval, context=self.get_serializer_context())
        return Response(output.data)


class RequestDocumentDownloadView(APIView):
    """Download a document attached to a request, with authorization checks."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["dristi_requests"],
        operation_id="requests_documents_download",
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    def get(self, request, request_id, document_id):
        """Stream the document if the caller is allowed to see it."""
        document = get_object_or_404(
            RequestDocument.objects.select_related("request"),
            pk=document_id,
            request_id=request_id,
        )
        if not services.can_access_document(request.user, document):
            raise Http404

        return FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=document.filename,
        )
