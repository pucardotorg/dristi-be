"""Bulk generation: chunking, fan-out, merge and aggregation (spec 0016 #11).

A template is bulk when its ``data_config`` declares ``bulk``::

    "bulk": {"records_path": "$.records", "merge": true, "merge_partial": false,
             "max_records_per_document": 100, "bulk_only": true}

The records found at ``records_path`` are split into chunks of at most
``max_records_per_document`` (default ``PDF_MAX_RECORDS_PER_DOCUMENT``), one
``PDFJobRecord`` per chunk. Each chunk renders one document with a section per
record. While mapping a record, ``data`` is the record itself and ``request``
is the whole request payload, so shared values stay reachable.

At most ``PDF_BULK_MAX_PARALLEL_CHUNKS`` chunks are queued at any time; each
finished chunk schedules the next one, and the last one schedules
``finalize_bulk_pdf``. Finalization merges chunk documents when configured --
by default only when every chunk succeeded (open question 9;
``merge_partial: true`` merges the successful chunks of a partial job too) --
and sets ``COMPLETED``, ``PARTIAL_SUCCESS`` or ``FAILED``.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from ..exceptions import PDFError, PDFRequestDataError
from ..models import (
    PDFJob,
    PDFJobRecord,
    PDFJobRecordStatus,
    PDFJobStatus,
)
from ..renderer.merge import merge
from .config_loader import LoadedConfig, PDFConfigLoader
from .context import RequestContext
from .documents import delete_documents, read_document, store_document, tags_for
from .generator import (
    claim_job,
    document_filename,
    log_event,
    render_variables,
    uploader_id,
)
from .mapping import DataMapper
from .mapping.direct import find_first
from .validation import validate_request_data

logger = logging.getLogger("apps.pdf")

DEFAULT_RECORDS_PATH = "$.records"


def is_bulk_config(data_config: dict) -> bool:
    """Whether a template generates bulk jobs."""
    return bool((data_config or {}).get("bulk") is not None)


def extract_records(data_config: dict, request_data) -> list:
    """Return the record list of a bulk request, or raise ``PDFRequestDataError``."""
    bulk = data_config.get("bulk") or {}
    records = find_first(bulk.get("records_path", DEFAULT_RECORDS_PATH), request_data, None)
    if not isinstance(records, list) or not records:
        raise PDFRequestDataError("A bulk request must contain a non-empty list of records.")
    return records


def records_per_document(data_config: dict) -> int:
    """Return the chunk size for a template."""
    bulk = data_config.get("bulk") or {}
    return int(bulk.get("max_records_per_document") or settings.PDF_MAX_RECORDS_PER_DOCUMENT)


def plan_chunks(total: int, size: int) -> list[tuple[int, int]]:
    """Return ``(offset, count)`` per chunk: 1000 records at 100 per document -> 10 chunks."""
    return [(offset, min(size, total - offset)) for offset in range(0, total, size)]


# ---------------------------------------------------------------------------
# Planning / fan-out
# ---------------------------------------------------------------------------


def start_bulk_job(job_id, attempt: int = 0) -> list[int]:
    """Claim a bulk job, create its chunk rows and return the sequences to enqueue."""
    job = claim_job(job_id, attempt)
    if job is None:
        return []

    config = PDFConfigLoader.load_version(job.template_version_id)
    records = extract_records(config.data_config, job.request_data)
    chunks = plan_chunks(len(records), records_per_document(config.data_config))
    PDFJobRecord.objects.bulk_create(
        [
            PDFJobRecord(job=job, sequence=sequence, offset=offset, count=count)
            for sequence, (offset, count) in enumerate(chunks)
        ],
        ignore_conflicts=True,  # a redelivered message re-plans idempotently
    )
    log_event("PDF_BULK_PLANNED", job, records=len(records), chunks=len(chunks))
    return schedule_chunks(job_id)


def schedule_chunks(job_id) -> list[int]:
    """Mark up to the parallelism budget of pending chunks ``QUEUED``; return them."""
    with transaction.atomic():
        job = PDFJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.status != PDFJobStatus.PROCESSING:
            return []
        in_flight = job.records.filter(
            status__in=(PDFJobRecordStatus.QUEUED, PDFJobRecordStatus.PROCESSING)
        ).count()
        budget = max(settings.PDF_BULK_MAX_PARALLEL_CHUNKS - in_flight, 0)
        if not budget:
            return []
        sequences = list(
            job.records.filter(status=PDFJobRecordStatus.PENDING)
            .order_by("sequence")
            .values_list("sequence", flat=True)[:budget]
        )
        job.records.filter(sequence__in=sequences).update(status=PDFJobRecordStatus.QUEUED)
    return sequences


def all_chunks_done(job_id) -> bool:
    """Whether every chunk of the job has reached a terminal status."""
    return not PDFJobRecord.objects.filter(
        job_id=job_id,
        status__in=(
            PDFJobRecordStatus.PENDING,
            PDFJobRecordStatus.QUEUED,
            PDFJobRecordStatus.PROCESSING,
        ),
    ).exists()


# ---------------------------------------------------------------------------
# One chunk
# ---------------------------------------------------------------------------


def claim_record(job_id, sequence, attempt: int = 0) -> tuple[PDFJob, PDFJobRecord] | None:
    """Move a chunk to ``PROCESSING``; ``None`` when it should not run.

    A chunk whose job was cancelled is marked ``CANCELLED`` here, at the chunk
    boundary, so no further work starts for a cancelled job (#12). As with
    jobs, a chunk is only claimed by the message for its current attempt.
    """
    with transaction.atomic():
        record = (
            PDFJobRecord.objects.select_for_update()
            .select_related("job")
            .filter(job_id=job_id, sequence=sequence)
            .first()
        )
        if record is None or record.is_terminal:
            return None
        job = record.job
        if job.status == PDFJobStatus.CANCELLED:
            record.status = PDFJobRecordStatus.CANCELLED
            record.save(update_fields=["status", "updated_at"])
            return None
        if job.status != PDFJobStatus.PROCESSING or record.attempt_count != attempt:
            return None
        record.status = PDFJobRecordStatus.PROCESSING
        record.attempt_count += 1
        record.save(update_fields=["status", "attempt_count", "updated_at"])
        return job, record


def _record_contexts(config: LoadedConfig, job: PDFJob, record: PDFJobRecord) -> list[dict]:
    records = extract_records(config.data_config, job.request_data)
    context = RequestContext.for_job(job)
    contexts = []
    for item in records[record.offset : record.offset + record.count]:
        validate_request_data(config.data_config, item)
        mapper = DataMapper(context, config.data_config)
        contexts.append(mapper.map(config.data_config, item, {"request": job.request_data}))
    return contexts


def generate_record(job_id, sequence, attempt: int = 0) -> None:
    """Render and persist one chunk.

    Raises ``PDFError`` for the actor to classify; the record is left
    ``PROCESSING`` so the retry can re-claim it.
    """
    claimed = claim_record(job_id, sequence, attempt)
    if claimed is None:
        return
    job, record = claimed

    config = PDFConfigLoader.load_version(job.template_version_id)
    contexts = _record_contexts(config, job, record)
    content = render_variables(config, contexts)

    if PDFJob.objects.filter(pk=job_id, status=PDFJobStatus.CANCELLED).exists():
        _set_record_status(record, PDFJobRecordStatus.CANCELLED)
        return

    file_id = store_document(
        content,
        filename=document_filename(config, contexts[0], suffix=f"part-{sequence + 1}"),
        user_id=uploader_id(job),
        organization_id=job.organization_id,
        tags=tags_for(job.key, job.entity_id),
    )

    with transaction.atomic():
        locked_job = PDFJob.objects.select_for_update().get(pk=job_id)
        locked = PDFJobRecord.objects.select_for_update().get(pk=record.pk)
        keep = locked_job.status == PDFJobStatus.PROCESSING and not locked.is_terminal
        if keep:
            locked.status = PDFJobRecordStatus.COMPLETED
            locked.file_id = file_id
            locked.error_code = ""
            locked.error_message = ""
            locked.save(
                update_fields=["status", "file_id", "error_code", "error_message", "updated_at"]
            )
        elif not locked.is_terminal:
            locked.status = PDFJobRecordStatus.CANCELLED
            locked.save(update_fields=["status", "updated_at"])
    if not keep:
        delete_documents([file_id])
    logger.info(
        "event=PDF_CHUNK_%s job_id=%s sequence=%s records=%s",
        "COMPLETED" if keep else "DISCARDED",
        job_id,
        sequence,
        record.count,
    )


def fail_record(job_id, sequence, error: PDFError) -> None:
    """Mark one chunk ``FAILED`` with a sanitized reason."""
    with transaction.atomic():
        record = (
            PDFJobRecord.objects.select_for_update()
            .filter(job_id=job_id, sequence=sequence)
            .first()
        )
        if record is None or record.is_terminal:
            return
        record.status = PDFJobRecordStatus.FAILED
        record.error_code = error.code
        record.error_message = error.safe_message[:512]
        record.save(update_fields=["status", "error_code", "error_message", "updated_at"])
    logger.warning(
        "event=PDF_CHUNK_FAILED job_id=%s sequence=%s error_code=%s", job_id, sequence, error.code
    )


def _set_record_status(record: PDFJobRecord, status: str) -> None:
    PDFJobRecord.objects.filter(pk=record.pk).exclude(
        status__in=(
            PDFJobRecordStatus.COMPLETED,
            PDFJobRecordStatus.FAILED,
            PDFJobRecordStatus.CANCELLED,
        )
    ).update(status=status)


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def finalize_job(job_id) -> None:
    """Merge (when configured) and record the aggregate outcome of a bulk job."""
    job = PDFJob.objects.filter(pk=job_id).first()
    if job is None or job.status != PDFJobStatus.PROCESSING or not all_chunks_done(job_id):
        return

    config = PDFConfigLoader.load_version(job.template_version_id)
    records = list(job.records.order_by("sequence"))
    succeeded = [record for record in records if record.status == PDFJobRecordStatus.COMPLETED]
    completed = sum(record.count for record in succeeded)
    failed = job.total_count - completed

    bulk = config.data_config.get("bulk") or {}
    should_merge = (
        bool(bulk.get("merge"))
        and len(succeeded) > 1
        and (failed == 0 or bulk.get("merge_partial", False))
    )
    merged_id = None
    if should_merge:
        content = merge([read_document(record.file_id) for record in succeeded])
        merged_id = store_document(
            content,
            filename=document_filename(config, {"meta": {"entity_id": job.entity_id}}),
            user_id=uploader_id(job),
            organization_id=job.organization_id,
            tags=tags_for(job.key, job.entity_id),
        )

    with transaction.atomic():
        locked = PDFJob.objects.select_for_update().get(pk=job_id)
        if locked.status != PDFJobStatus.PROCESSING:
            if merged_id:
                transaction.on_commit(lambda: delete_documents([merged_id]))
            return
        locked.file_ids = [merged_id] if merged_id else [r.file_id for r in succeeded]
        locked.completed_count = completed
        locked.failed_count = failed
        if not succeeded:
            first_failure = next(
                (r for r in records if r.status == PDFJobRecordStatus.FAILED), None
            )
            locked.error_code = first_failure.error_code if first_failure else "PDF_BULK_FAILED"
            locked.error_message = "Every chunk of the bulk job failed."
            locked.transition_to(PDFJobStatus.FAILED)
        elif failed:
            locked.error_code = "PDF_BULK_PARTIAL"
            locked.error_message = f"{failed} of {locked.total_count} records failed."
            locked.transition_to(PDFJobStatus.PARTIAL_SUCCESS)
        else:
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
    log_event(
        "PDF_BULK_FINALIZED",
        locked,
        completed=completed,
        failed=failed,
        merged=bool(merged_id),
        level=logging.WARNING if failed else logging.INFO,
    )


def completed_record_count(job_id) -> int:
    """Return how many records the job's completed chunks cover."""
    return (
        PDFJobRecord.objects.filter(job_id=job_id, status=PDFJobRecordStatus.COMPLETED).aggregate(
            total=Sum("count")
        )["total"]
        or 0
    )
