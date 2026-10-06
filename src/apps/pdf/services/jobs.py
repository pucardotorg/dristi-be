"""Job lifecycle services used by the API (spec 0016 #4, #12).

Views stay thin: they validate input with serializers and call these
functions, which own the transactions, reuse decisions and enqueueing.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from functools import partial

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from ..exceptions import PDFError, PDFJobStateError, PDFRenderError
from ..models import (
    CANCELLABLE_JOB_STATUSES,
    PDFJob,
    PDFJobRecordStatus,
    PDFJobStatus,
)
from .bulk import extract_records, is_bulk_config
from .config_loader import PDFConfigLoader
from .context import RequestContext
from .documents import delete_documents
from .generator import log_event, render_document
from .reuse import compute_reuse_key, find_reusable_job
from .validation import validate_request_data

logger = logging.getLogger("apps.pdf")


class PDFSyncRenderTimeout(PDFError):  # noqa: N818
    """The synchronous render exceeded ``PDF_SYNC_RENDER_TIMEOUT_SECONDS``."""

    code = "PDF_SYNC_RENDER_TIMEOUT"
    default_message = "The document took too long to render; create a job instead."


class PDFSyncRenderNotAllowed(PDFError):  # noqa: N818
    """The template may not be rendered synchronously."""

    code = "PDF_SYNC_RENDER_NOT_ALLOWED"
    default_message = "This template cannot be rendered synchronously; create a job instead."


@dataclass(frozen=True)
class JobRequest:
    """Validated input for creating a job."""

    key: str
    tenant_id: str
    data: dict
    entity_id: str = ""
    organization_id: object = None
    locale: str = ""
    correlation_id: str = ""
    force_regenerate: bool = False


def create_job(request: JobRequest, *, user=None) -> tuple[PDFJob, bool]:
    """Create and enqueue a job, or return a reusable one.

    Returns ``(job, reused)``. Invalid request data is rejected here, before a
    row exists, when the template declares a ``request_schema``.
    """
    _, data_config, config = PDFConfigLoader.load(request.key)
    bulk = is_bulk_config(data_config)
    if bulk:
        total = len(extract_records(data_config, request.data))
    else:
        validate_request_data(data_config, request.data)
        total = 1

    reuse_key = compute_reuse_key(
        tenant_id=request.tenant_id,
        key=request.key,
        entity_id=request.entity_id,
        version=config.version,
        data_config=data_config,
        request_data=request.data,
    )
    if not request.force_regenerate:
        existing = find_reusable_job(reuse_key)
        if existing is not None:
            log_event("PDF_JOB_REUSED", existing)
            return existing, True

    with transaction.atomic():
        job = PDFJob.objects.create(
            key=request.key,
            template_version_id=config.template_version_id,
            tenant_id=request.tenant_id,
            entity_id=request.entity_id,
            organization_id=request.organization_id,
            requested_by=user if getattr(user, "is_authenticated", False) else None,
            created_by=user if getattr(user, "is_authenticated", False) else None,
            locale=request.locale,
            correlation_id=request.correlation_id,
            is_bulk=bulk,
            reuse_key=reuse_key,
            request_data=request.data,
            total_count=total,
        )
        job.transition_to(PDFJobStatus.QUEUED)
        job.save(update_fields=["status", "queued_at", "updated_at"])
        transaction.on_commit(partial(_enqueue, job))
    log_event("PDF_JOB_CREATED", job, bulk=bulk, total=total)
    return job, False


def _enqueue(job: PDFJob) -> None:
    from ..tasks import generate_bulk_pdf, generate_pdf

    actor = generate_bulk_pdf if job.is_bulk else generate_pdf
    actor.send(str(job.id), 0)
    log_event("PDF_JOB_QUEUED", job)


def cancel_job(job_id) -> PDFJob:
    """Cancel a non-terminal job; raise ``PDFJobStateError`` for terminal ones.

    Pending chunks are cancelled immediately; chunks already running finish
    their in-flight work but their output is discarded (#12). Documents
    already persisted for the job are deleted through the File Storage Service.
    """
    with transaction.atomic():
        job = PDFJob.objects.select_for_update().get(pk=job_id)
        if job.status not in CANCELLABLE_JOB_STATUSES:
            raise PDFJobStateError(f"A {job.status} job cannot be cancelled.")
        job.transition_to(PDFJobStatus.CANCELLED)
        job.save(update_fields=["status", "completed_at", "updated_at"])
        job.records.filter(
            status__in=(PDFJobRecordStatus.PENDING, PDFJobRecordStatus.QUEUED)
        ).update(status=PDFJobRecordStatus.CANCELLED, updated_at=timezone.now())
        persisted = list(job.records.exclude(file_id="").values_list("file_id", flat=True)) + list(
            job.file_ids or []
        )
    log_event("PDF_JOB_CANCELLED", job)
    if persisted:
        _delete_job_files(job, persisted)
    return job


def delete_job_documents(job: PDFJob) -> PDFJob:
    """Delete every document a job produced and mark it no longer downloadable."""
    file_ids = list(job.file_ids or []) + list(
        job.records.exclude(file_id="").values_list("file_id", flat=True)
    )
    remaining = delete_documents(list(dict.fromkeys(file_ids)))
    with transaction.atomic():
        locked = PDFJob.objects.select_for_update().get(pk=job.pk)
        locked.file_ids = [file_id for file_id in locked.file_ids if file_id in remaining]
        locked.records.exclude(file_id__in=remaining).update(file_id="")
        if not remaining:
            locked.files_deleted_at = timezone.now()
        locked.save(update_fields=["file_ids", "files_deleted_at", "updated_at"])
    if remaining:
        raise PDFJobStateError("Some documents could not be deleted; retry the request.")
    log_event("PDF_JOB_DOCUMENTS_DELETED", locked, count=len(file_ids))
    return locked


def _delete_job_files(job: PDFJob, file_ids: list[str]) -> None:
    remaining = delete_documents(list(dict.fromkeys(file_ids)))
    PDFJob.objects.filter(pk=job.pk).update(
        file_ids=[file_id for file_id in job.file_ids if file_id in remaining],
        files_deleted_at=None if remaining else timezone.now(),
    )
    job.records.exclude(file_id__in=remaining).update(file_id="")


def render_sync(
    key: str, tenant_id: str, data: dict, *, locale: str = "", correlation_id: str = "", user=None
) -> bytes:
    """Render a document in-process without creating a job or storing anything.

    Rejects bulk templates, templates that need external API mapping, and
    templates that opt out with ``sync_render: false`` (#4.3). The caller gets
    an answer within ``PDF_SYNC_RENDER_TIMEOUT_SECONDS``: the render runs on a
    worker thread and a timeout is reported as soon as the deadline passes.
    Python cannot kill that thread, so an overrunning render finishes in the
    background and its result is dropped; the size limits on images and
    mappings bound how long that can take.
    """
    _, data_config, config = PDFConfigLoader.load(key)
    if is_bulk_config(data_config) or data_config.get("sync_render") is False:
        raise PDFSyncRenderNotAllowed()
    if any(spec.get("type") == "external_api" for spec in data_config.get("mappings", [])):
        raise PDFSyncRenderNotAllowed(
            "Templates that call external APIs cannot be rendered synchronously."
        )

    context = RequestContext(
        tenant_id=tenant_id,
        key=key,
        locale=locale or RequestContext.__dataclass_fields__["locale"].default,
        correlation_id=correlation_id,
        user_id=str(getattr(user, "pk", "") or ""),
    )
    timeout = settings.PDF_SYNC_RENDER_TIMEOUT_SECONDS
    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-sync")
    future = executor.submit(_render_in_thread, config, data, context)
    try:
        content = future.result(timeout=timeout)
    except FutureTimeout as exc:
        logger.warning("event=PDF_SYNC_RENDER_TIMEOUT key=%s timeout_s=%s", key, timeout)
        raise PDFSyncRenderTimeout() from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    logger.info(
        "event=PDF_SYNC_RENDERED key=%s version=%s duration_ms=%d",
        key,
        config.version,
        (time.monotonic() - started) * 1000,
    )
    return content


def _render_in_thread(config, data, context) -> bytes:
    try:
        return render_document(config, data, context)
    except PDFError:
        raise
    except Exception as exc:  # pragma: no cover - defensive: never leak internals
        raise PDFRenderError() from exc
    finally:
        close_old_connections()


__all__ = [
    "JobRequest",
    "PDFSyncRenderNotAllowed",
    "PDFSyncRenderTimeout",
    "cancel_job",
    "create_job",
    "delete_job_documents",
    "render_sync",
]
