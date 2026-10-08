"""Generation orchestration for one document (spec 0016 #5).

``render_document`` is the pure part -- configuration + data in, PDF bytes out
-- shared by the synchronous render endpoint, single jobs and bulk chunks.
``generate_job`` adds the job bookkeeping: claim, render, persist through
``apps.files``, complete. Persistence happens strictly before ``COMPLETED`` is
recorded, and a cancelled job never gets a document persisted (#6, #12).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from ..exceptions import PDFConfigurationError, PDFError
from ..models import PDFJob, PDFJobStatus
from ..renderer import get_renderer
from .composer import compose, compose_many
from .config_loader import LoadedConfig, PDFConfigLoader
from .context import RequestContext
from .documents import delete_documents, resolve_system_user_id, store_document, tags_for
from .mapping import DataMapper
from .templating import render_text
from .validation import validate_request_data

logger = logging.getLogger("apps.pdf")


def log_event(event: str, job: PDFJob | None = None, level=logging.INFO, **fields) -> None:
    """Emit one structured line for a job lifecycle event (#16)."""
    if job is not None:
        fields = {
            "job_id": job.id,
            "key": job.key,
            "template_version": job.template_version_id,
            "tenant_id": job.tenant_id,
            "status": job.status,
            "correlation_id": job.correlation_id,
            **fields,
        }
    logger.log(
        level,
        "event=%s %s",
        event,
        " ".join(f"{name}={value}" for name, value in fields.items()),
    )


def build_context(config: LoadedConfig, request_data, context: RequestContext) -> dict:
    """Validate request data and run the ``DataMapper``."""
    validate_request_data(config.data_config, request_data)
    return DataMapper(context, config.data_config).map(config.data_config, request_data)


def render_document(config: LoadedConfig, request_data, context: RequestContext) -> bytes:
    """Render one document for ``request_data``."""
    variables = build_context(config, request_data, context)
    return render_variables(config, [variables])


def render_variables(config: LoadedConfig, contexts: list[dict]) -> bytes:
    """Compose and render already-mapped contexts (one section per context)."""
    try:
        if len(contexts) == 1:
            document = compose(config.format_config, contexts[0])
        else:
            document = compose_many(config.format_config, contexts)
    except (KeyError, TypeError) as exc:
        raise PDFConfigurationError("The format configuration could not be applied.") from exc

    started = time.monotonic()
    content = get_renderer().render(document, contexts[0])
    duration_ms = (time.monotonic() - started) * 1000
    logger.info(
        "event=PDF_RENDERED key=%s version=%s sections=%s bytes=%s duration_ms=%d",
        config.key,
        config.version,
        len(contexts),
        len(content),
        duration_ms,
    )
    return content


def document_filename(config: LoadedConfig, variables: dict, suffix: str = "") -> str:
    """Return the stored filename, from ``data_config.filename`` when declared."""
    template = config.data_config.get("filename")
    if template:
        try:
            name = render_text(template, variables, escape_output=False).strip()
        except PDFError:
            name = ""
    else:
        name = ""
    if not name:
        entity = variables.get("meta", {}).get("entity_id") or ""
        name = "-".join(part for part in (config.key, entity) if part)
    if suffix:
        name = f"{name}-{suffix}"
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def uploader_id(job: PDFJob):
    """Return the user to attribute a job's documents to."""
    return job.requested_by_id or resolve_system_user_id()


# ---------------------------------------------------------------------------
# Job state helpers (all re-read the row under a lock)
# ---------------------------------------------------------------------------


def claim_job(job_id, attempt: int = 0) -> PDFJob | None:
    """Move a queued job to ``PROCESSING``; return ``None`` when there is nothing to do.

    Every message carries the attempt number it was sent for, and a job is
    only claimed when its ``attempt_count`` still equals that number. The
    first delivery of attempt 0 claims a ``QUEUED`` job; a retry message
    (attempt n) re-claims the ``PROCESSING`` job left by attempt n-1. A
    duplicate delivery finds the counter already advanced, and deliveries for
    cancelled or finished jobs find a terminal status: both return ``None``,
    so duplicates never produce a second document (#10).
    """
    with transaction.atomic():
        job = PDFJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.is_terminal or job.status == PDFJobStatus.CREATED:
            return None
        if job.attempt_count != attempt:
            return None
        if job.status == PDFJobStatus.QUEUED:
            job.transition_to(PDFJobStatus.PROCESSING)
        job.attempt_count += 1
        job.save(update_fields=["status", "started_at", "attempt_count", "updated_at"])
        log_event("PDF_JOB_PROCESSING", job, attempt=job.attempt_count)
        return job


def fail_job(job_id, error: PDFError) -> None:
    """Record a terminal failure (no-op if the job already finished)."""
    with transaction.atomic():
        job = PDFJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.is_terminal:
            return
        if job.status == PDFJobStatus.QUEUED:
            job.transition_to(PDFJobStatus.PROCESSING)
        job.transition_to(PDFJobStatus.FAILED)
        job.error_code = error.code
        job.error_message = error.safe_message[:512]
        job.save(
            update_fields=[
                "status",
                "error_code",
                "error_message",
                "started_at",
                "completed_at",
                "updated_at",
            ]
        )
    log_event("PDF_JOB_FAILED", job, level=logging.WARNING, error_code=error.code, failed_at=_iso())


def _iso(value: datetime | None = None) -> str:
    return (value or timezone.now()).isoformat()


# ---------------------------------------------------------------------------
# Single-document generation
# ---------------------------------------------------------------------------


def generate_job(job_id, attempt: int = 0) -> None:
    """Generate, persist and complete a single-document job.

    Raises ``PDFError`` for the caller (the actor) to classify as retryable or
    terminal.
    """
    job = claim_job(job_id, attempt)
    if job is None:
        return

    config = PDFConfigLoader.load_version(job.template_version_id)
    context = RequestContext.for_job(job)
    variables = build_context(config, job.request_data, context)
    content = render_variables(config, [variables])
    filename = document_filename(config, variables)

    if _is_cancelled(job_id):
        log_event("PDF_JOB_CANCELLED_BEFORE_PERSIST", job)
        return

    file_id = store_document(
        content,
        filename=filename,
        user_id=uploader_id(job),
        organization_id=job.organization_id,
        tags=tags_for(job.key, job.entity_id),
    )

    with transaction.atomic():
        locked = PDFJob.objects.select_for_update().get(pk=job_id)
        if locked.status != PDFJobStatus.PROCESSING:
            # Cancelled (or completed by a concurrent delivery) while the
            # document was being stored: the upload is not ours to keep.
            orphan = [file_id]
        else:
            orphan = []
            locked.file_ids = [file_id]
            locked.completed_count = 1
            locked.failed_count = 0
            locked.error_code = ""
            locked.error_message = ""
            locked.transition_to(PDFJobStatus.COMPLETED)
            locked.save(
                update_fields=[
                    "file_ids",
                    "completed_count",
                    "failed_count",
                    "error_code",
                    "error_message",
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )
    if orphan:
        delete_documents(orphan)
        log_event("PDF_JOB_RESULT_DISCARDED", locked)
        return

    duration = (locked.completed_at - locked.started_at).total_seconds() if locked.started_at else 0
    log_event("PDF_JOB_COMPLETED", locked, file_count=1, duration_s=f"{duration:.3f}")


def _is_cancelled(job_id) -> bool:
    return PDFJob.objects.filter(pk=job_id, status=PDFJobStatus.CANCELLED).exists()
