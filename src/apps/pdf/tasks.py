"""Dramatiq actors for PDF generation (spec 0016 #10, #11).

Actors receive identifiers only -- the job id, the chunk sequence and the
attempt number -- never payloads. Each attempt is a separate message: a failed
attempt either schedules attempt ``n + 1`` with exponential backoff or records
a terminal failure, according to the dependency-specific policy:

=====================================  =====================================
Failure                                Behaviour
=====================================  =====================================
External API / localization / image    retry with backoff, bounded by
(``PDFDependencyError``)               ``PDF_JOB_MAX_RETRIES``
File storage (``PDFStorageError``)     retry with backoff (bounded)
Database connectivity                  retry with backoff (bounded)
Invalid configuration / request data   no retry, ``FAILED``
Renderer error on valid config         retry once, then ``FAILED``
=====================================  =====================================

Dramatiq's own Retries middleware is disabled (``max_retries=0``) so that
retries are decided here, per failure class, and the attempt number travels in
the message to make duplicate deliveries harmless.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import InterfaceError, OperationalError
from dramatiq import actor

from .exceptions import PDFDependencyError, PDFError, PDFRenderError, PDFStorageError
from .services import bulk
from .services.generator import fail_job, generate_job

logger = logging.getLogger("apps.pdf")

QUEUE = "pdf"


class _DatabaseUnavailable(PDFError):  # noqa: N818
    code = "PDF_DATABASE_UNAVAILABLE"
    retryable = True
    default_message = "The database was unavailable while generating the document."


class _UnexpectedError(PDFError):  # noqa: N818
    code = "PDF_INTERNAL_ERROR"
    default_message = "The document could not be generated."


def classify(exc: BaseException) -> PDFError:
    """Map any exception to the ``PDFError`` that decides its retry policy."""
    if isinstance(exc, PDFError):
        return exc
    if isinstance(exc, OperationalError | InterfaceError):
        return _DatabaseUnavailable()
    return _UnexpectedError()


def should_retry(error: PDFError, attempt: int) -> bool:
    """Return whether attempt ``attempt`` (0-based) may be followed by another."""
    if isinstance(error, PDFRenderError):
        return attempt < 1
    if isinstance(error, PDFDependencyError | PDFStorageError) or error.retryable:
        return attempt < settings.PDF_JOB_MAX_RETRIES
    return False


def retry_delay_ms(attempt: int) -> int:
    """Exponential backoff for the attempt after ``attempt``."""
    base = settings.PDF_RETRY_DELAY_BASE_SECONDS
    delay = base * (2**attempt)
    return int(min(delay, settings.PDF_RETRY_DELAY_MAX_SECONDS) * 1000)


def _handle_failure(exc, attempt, *, retry, fail, what: str, **ids) -> None:
    error = classify(exc)
    if should_retry(error, attempt):
        delay = retry_delay_ms(attempt)
        logger.warning(
            "event=PDF_RETRY_SCHEDULED %s error_code=%s attempt=%s delay_ms=%s",
            " ".join(f"{k}={v}" for k, v in ids.items()),
            error.code,
            attempt + 1,
            delay,
        )
        retry(delay)
        return
    if not isinstance(exc, PDFError):
        logger.exception("event=PDF_UNEXPECTED_ERROR what=%s", what, exc_info=exc)
    logger.warning(
        "event=PDF_RETRY_EXHAUSTED %s error_code=%s attempts=%s",
        " ".join(f"{k}={v}" for k, v in ids.items()),
        error.code,
        attempt + 1,
    )
    fail(error)


@actor(queue_name=QUEUE, max_retries=0, time_limit=settings.PDF_TASK_TIME_LIMIT_MS)
def generate_pdf(job_id: str, attempt: int = 0) -> None:
    """Generate a single-document job."""
    try:
        generate_job(job_id, attempt)
    except Exception as exc:
        _handle_failure(
            exc,
            attempt,
            retry=lambda delay: generate_pdf.send_with_options(
                args=(job_id, attempt + 1), delay=delay
            ),
            fail=lambda error: fail_job(job_id, error),
            what="generate_pdf",
            job_id=job_id,
        )


@actor(queue_name=QUEUE, max_retries=0, time_limit=settings.PDF_TASK_TIME_LIMIT_MS)
def generate_bulk_pdf(job_id: str, attempt: int = 0) -> None:
    """Plan the chunks of a bulk job and fan out the first batch."""
    try:
        sequences = bulk.start_bulk_job(job_id, attempt)
    except Exception as exc:
        _handle_failure(
            exc,
            attempt,
            retry=lambda delay: generate_bulk_pdf.send_with_options(
                args=(job_id, attempt + 1), delay=delay
            ),
            fail=lambda error: fail_job(job_id, error),
            what="generate_bulk_pdf",
            job_id=job_id,
        )
        return
    for sequence in sequences:
        generate_pdf_record.send(job_id, sequence, 0)


@actor(queue_name=QUEUE, max_retries=0, time_limit=settings.PDF_TASK_TIME_LIMIT_MS)
def generate_pdf_record(job_id: str, sequence: int, attempt: int = 0) -> None:
    """Generate one bulk chunk, then schedule more chunks or finalization."""
    try:
        bulk.generate_record(job_id, sequence, attempt)
    except Exception as exc:
        retried = []
        _handle_failure(
            exc,
            attempt,
            retry=lambda delay: retried.append(
                generate_pdf_record.send_with_options(
                    args=(job_id, sequence, attempt + 1), delay=delay
                )
            ),
            fail=lambda error: bulk.fail_record(job_id, sequence, error),
            what="generate_pdf_record",
            job_id=job_id,
            sequence=sequence,
        )
        if retried:
            return
    _advance(job_id)


def _advance(job_id: str) -> None:
    """Queue the next chunks within the parallelism budget, or finalize."""
    for sequence in bulk.schedule_chunks(job_id):
        generate_pdf_record.send(job_id, sequence, 0)
    if bulk.all_chunks_done(job_id):
        finalize_bulk_pdf.send(job_id, 0)


@actor(queue_name=QUEUE, max_retries=0, time_limit=settings.PDF_TASK_TIME_LIMIT_MS)
def finalize_bulk_pdf(job_id: str, attempt: int = 0) -> None:
    """Merge chunk documents when configured and record the aggregate status.

    Several chunks can finish together and each may send this message;
    ``finalize_job`` locks the job and only the first one does any work.
    """
    try:
        bulk.finalize_job(job_id)
    except Exception as exc:
        _handle_failure(
            exc,
            attempt,
            retry=lambda delay: finalize_bulk_pdf.send_with_options(
                args=(job_id, attempt + 1), delay=delay
            ),
            fail=lambda error: fail_job(job_id, error),
            what="finalize_bulk_pdf",
            job_id=job_id,
        )
