"""Startup validation of the PDF settings (spec 0016 #15)."""

from django.conf import settings
from django.core.checks import Error, register

POSITIVE_INT_SETTINGS = (
    "PDF_EXTERNAL_API_TIMEOUT_SECONDS",
    "PDF_IMAGE_DOWNLOAD_TIMEOUT_SECONDS",
    "PDF_IMAGE_MAX_BYTES",
    "PDF_MAX_RECORDS_PER_DOCUMENT",
    "PDF_BULK_MAX_PARALLEL_CHUNKS",
    "PDF_SYNC_RENDER_TIMEOUT_SECONDS",
    "PDF_CONFIG_CACHE_TIMEOUT_SECONDS",
    "PDF_LOCALIZATION_CACHE_TIMEOUT_SECONDS",
    "PDF_SIGNATURE_CONTAINER_BYTES",
    "PDF_MAX_SIGN_INPUT_BYTES",
    "PDF_MAX_REQUEST_DATA_BYTES",
    "PDF_EXTERNAL_API_MAX_CALLS_PER_JOB",
    "PDF_TASK_TIME_LIMIT_MS",
)
NON_NEGATIVE_INT_SETTINGS = (
    "PDF_EXTERNAL_API_MAX_RETRIES",
    "PDF_JOB_MAX_RETRIES",
    "PDF_RETRY_DELAY_BASE_SECONDS",
    "PDF_RETRY_DELAY_MAX_SECONDS",
)


def _int_error(name, minimum):
    value = getattr(settings, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return Error(
            f"{name} must be an integer of at least {minimum}, got {value!r}.",
            hint=f"Set {name} in settings or the environment.",
            id=f"pdf.E001.{name}",
        )
    return None


@register()
def check_pdf_settings(app_configs, **kwargs):
    """Validate PDF numeric settings and the signing hash algorithm."""
    from .services.signing import SUPPORTED_HASH_ALGORITHMS

    errors = [_int_error(name, 1) for name in POSITIVE_INT_SETTINGS]
    errors += [_int_error(name, 0) for name in NON_NEGATIVE_INT_SETTINGS]
    errors = [error for error in errors if error is not None]

    algorithm = str(getattr(settings, "PDF_SIGNATURE_HASH_ALGORITHM", "")).upper().replace("-", "")
    if algorithm not in SUPPORTED_HASH_ALGORITHMS:
        errors.append(
            Error(
                "PDF_SIGNATURE_HASH_ALGORITHM must be one of "
                f"{', '.join(sorted(SUPPORTED_HASH_ALGORITHMS))}.",
                id="pdf.E002",
            )
        )
    container = getattr(settings, "PDF_SIGNATURE_CONTAINER_BYTES", 0)
    if isinstance(container, int) and not isinstance(container, bool) and container < 4096:
        errors.append(
            Error(
                "PDF_SIGNATURE_CONTAINER_BYTES must be at least 4096 to hold a PKCS#7 blob.",
                id="pdf.E003",
            )
        )
    credentials = getattr(settings, "PDF_SERVICE_CREDENTIALS", {})
    if not isinstance(credentials, dict) or not all(
        isinstance(headers, dict) for headers in credentials.values()
    ):
        errors.append(
            Error(
                "PDF_SERVICE_CREDENTIALS must map names to header dictionaries.",
                id="pdf.E004",
            )
        )
    return errors
