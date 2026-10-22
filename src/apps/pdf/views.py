"""PDF API views (spec 0016 #4).

Views validate input, call ``apps.pdf.services.jobs`` and serialize the
result. Mapping, rendering and storage happen in services and workers.

A job belongs to the user who requested it. Every job endpoint -- search,
retrieve, cancel, download and delete -- operates only on the caller's own
jobs; there is no staff override. Another user's job id answers ``404``, the
same as an unknown id, so ids cannot be probed.
"""

from django.http import FileResponse, HttpResponse
from django.utils.text import get_valid_filename
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.api.schema import error_responses
from apps.api.viewsets import APIModelReadOnlyViewSet

from . import errors
from .exceptions import PDFError
from .models import PDFJob
from .serializers import (
    PDFDownloadQuerySerializer,
    PDFJobCreateSerializer,
    PDFJobFilterSerializer,
    PDFJobSerializer,
    PDFRenderRequestSerializer,
)
from .services import jobs
from .services.documents import PDFDocumentNotFound, open_document

CORRELATION_HEADER = "HTTP_X_CORRELATION_ID"

# Failures any template render can hit, synchronous or queued.
RENDER_ERRORS = (
    errors.TEMPLATE_NOT_FOUND.example("No active PDF template for key 'case-summons'."),
    errors.INVALID_REQUEST_DATA.example(
        "Request data is invalid: (root): 'case' is a required property", field="data"
    ),
    errors.INVALID_CONFIG,
)


def _request_meta(request) -> dict:
    return {"correlation_id": request.META.get(CORRELATION_HEADER, "")[:128]}


def _pdf_filename(job: PDFJob, suffix: str = "") -> str:
    name = "-".join(part for part in (job.key, job.entity_id, suffix) if part)
    return f"{get_valid_filename(name) or 'document'}.pdf"


@extend_schema_view(
    list=extend_schema(
        parameters=[PDFJobFilterSerializer],
        responses=error_responses(
            api_errors.INVALID_CHOICE.example('"DONE" is not a valid choice.', field="status")
        ),
        summary="Search PDF jobs by entity, key, tenant or status.",
    ),
    retrieve=extend_schema(summary="Retrieve a PDF job; poll until file_ids appear."),
    create=extend_schema(
        request=PDFJobCreateSerializer,
        responses={
            202: PDFJobSerializer,
            200: PDFJobSerializer,
            **error_responses(
                *RENDER_ERRORS,
                api_errors.INCORRECT_TYPE.example("data must be a JSON object.", field="data"),
                api_errors.MAX_LENGTH.example("data exceeds the 2097152 byte limit.", field="data"),
            ),
        },
        summary="Create a generation job (202), or return a reusable one (200, reused=true).",
    ),
    destroy=extend_schema(
        responses={
            200: PDFJobSerializer,
            **error_responses(
                errors.JOB_ACTIVE,
                errors.STORAGE_UNAVAILABLE.example(
                    "Some documents could not be deleted; retry the request."
                ),
            ),
        },
        summary="Delete the job's generated documents.",
    ),
    cancel=extend_schema(
        request=None,
        responses={
            200: PDFJobSerializer,
            **error_responses(
                errors.INVALID_TRANSITION.example("A COMPLETED job cannot be cancelled.")
            ),
        },
        summary="Cancel a job that has not finished.",
    ),
    download=extend_schema(
        parameters=[
            OpenApiParameter("sequence", int, description="Bulk chunk sequence to download."),
            OpenApiParameter("index", int, description="Index into file_ids (default 0)."),
        ],
        responses={
            (200, "application/pdf"): OpenApiTypes.BINARY,
            **error_responses(
                api_errors.INVALID.example("sequence and index are mutually exclusive."),
                api_errors.INVALID.example("A valid integer is required.", field="index"),
                api_errors.MIN_VALUE.example(
                    "Ensure this value is greater than or equal to 0.", field="index"
                ),
                errors.NO_DOCUMENT,
                errors.NO_DOCUMENT.example("No document for that chunk."),
                errors.NO_DOCUMENT.example("The document no longer exists."),
            ),
        },
        summary="Download a generated document.",
    ),
)
class PDFJobViewSet(APIModelReadOnlyViewSet):
    """Create, search, retrieve, cancel, download and delete PDF jobs."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]
    serializer_class = PDFJobSerializer
    lookup_field = "id"

    def get_queryset(self):
        """Return only the caller's own jobs, filtered on list.

        Every detail action resolves its job through ``get_object()``, which
        uses this queryset, so ownership is enforced in one place for
        retrieve, cancel, download and delete alike.
        """
        if getattr(self, "swagger_fake_view", False):
            # Schema generation has no real user; the model is all it needs.
            return PDFJob.objects.none()
        queryset = PDFJob.objects.owned_by(self.request.user).select_related("template_version")
        if self.action == "list":
            filters = PDFJobFilterSerializer(data=self.request.query_params)
            filters.is_valid(raise_exception=True)
            queryset = queryset.filter(**filters.validated_data)
        return queryset

    def get_serializer_context(self):
        """Include chunk detail on single-job responses."""
        context = super().get_serializer_context()
        context["include_records"] = self.action != "list"
        return context

    def _respond(self, job, *, reused=False, status_code=status.HTTP_200_OK):
        context = {**self.get_serializer_context(), "reused": reused}
        return Response(PDFJobSerializer(job, context=context).data, status=status_code)

    def create(self, request, *args, **kwargs):
        """Validate, then create/enqueue a job or return the reusable one."""
        serializer = PDFJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        organization = params.get("organization_id")
        try:
            job, reused = jobs.create_job(
                jobs.JobRequest(
                    key=params["key"],
                    tenant_id=params["tenant_id"],
                    data=params["data"],
                    entity_id=params["entity_id"],
                    organization_id=organization.pk if organization else None,
                    locale=params["locale"],
                    force_regenerate=params["force_regenerate"],
                    **_request_meta(request),
                ),
                user=request.user,
            )
        except PDFError as exc:
            raise errors.api_error(exc) from exc
        return self._respond(
            job,
            reused=reused,
            status_code=status.HTTP_200_OK if reused else status.HTTP_202_ACCEPTED,
        )

    def destroy(self, request, *args, **kwargs):
        """Delete the job's documents through the File Storage Service."""
        job = self.get_object()
        if not job.is_terminal:
            raise BusinessError(errors.JOB_ACTIVE)
        try:
            job = jobs.delete_job_documents(job, user=request.user)
        except PDFError as exc:
            raise errors.api_error(exc) from exc
        return self._respond(job)

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        """Cancel a ``CREATED``/``QUEUED``/``PROCESSING`` job; terminal jobs conflict."""
        job = self.get_object()
        try:
            job = jobs.cancel_job(job.pk, user=request.user)
        except PDFError as exc:
            raise errors.api_error(exc) from exc
        return self._respond(job)

    @action(detail=True, methods=["get"])
    def download(self, request, *args, **kwargs):
        """Stream a document obtained from the File Storage Service."""
        job = self.get_object()
        query = PDFDownloadQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        suffix = ""
        if "sequence" in query.validated_data:
            sequence = query.validated_data["sequence"]
            record = job.records.filter(sequence=sequence).exclude(file_id="").first()
            if record is None:
                raise BusinessError(errors.NO_DOCUMENT, "No document for that chunk.")
            file_id, suffix = record.file_id, f"part-{sequence + 1}"
        else:
            index = query.validated_data.get("index", 0)
            if index >= len(job.file_ids or []):
                raise BusinessError(errors.NO_DOCUMENT)
            file_id = job.file_ids[index]
            if len(job.file_ids) > 1:
                suffix = f"part-{index + 1}"

        try:
            handle = open_document(file_id)
        except PDFDocumentNotFound as exc:
            raise BusinessError(errors.NO_DOCUMENT, "The document no longer exists.") from exc
        return FileResponse(
            handle,
            as_attachment=True,
            filename=_pdf_filename(job, suffix),
            content_type="application/pdf",
        )


class PDFRenderView(APIView):
    """Synchronous render: returns PDF bytes, stores nothing, creates no job."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]

    @extend_schema(
        request=PDFRenderRequestSerializer,
        responses={
            (200, "application/pdf"): OpenApiTypes.BINARY,
            **error_responses(
                *RENDER_ERRORS,
                errors.SYNC_RENDER_NOT_ALLOWED,
                errors.SYNC_RENDER_NOT_ALLOWED.example(
                    "Templates that call external APIs cannot be rendered synchronously."
                ),
                errors.SYNC_RENDER_TIMEOUT,
                errors.DEPENDENCY_UNAVAILABLE,
                errors.RENDER_FAILED,
            ),
        },
        summary="Render a small document synchronously.",
    )
    def post(self, request):
        """Render and return ``application/pdf`` bytes."""
        serializer = PDFRenderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        try:
            content = jobs.render_sync(
                params["key"],
                params["tenant_id"],
                params["data"],
                locale=params["locale"],
                user=request.user,
                **_request_meta(request),
            )
        except PDFError as exc:
            raise errors.api_error(exc) from exc
        response = HttpResponse(content, content_type="application/pdf")
        filename = get_valid_filename(params["key"]) or "document"
        response["Content-Disposition"] = f'inline; filename="{filename}.pdf"'
        return response
