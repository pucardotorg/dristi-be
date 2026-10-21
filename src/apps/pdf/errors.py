"""PDF API error codes (domain 04, spec 0000 section 9).

``PDFError.code`` (``PDF_TEMPLATE_NOT_FOUND`` …) stays what jobs record in
``error_code`` and the log; the codes here are what an endpoint returns in the
standard error body. ``api_error`` maps one onto the other.
"""

from apps.api import errors as api_errors
from apps.api.errors import BusinessError, define

from . import exceptions

TEMPLATE_NOT_FOUND = define(
    "E04001", "No active PDF template matches the requested key.", status=404
)
INVALID_REQUEST_DATA = define("E04002", "The request data does not satisfy the PDF template.")
SYNC_RENDER_NOT_ALLOWED = define(
    "E04003", "This template cannot be rendered synchronously; create a job instead."
)
SYNC_RENDER_TIMEOUT = define(
    "E04004", "The document took too long to render; create a job instead.", status=504
)
INVALID_TRANSITION = define("E04005", "The job cannot move to the requested status.", status=409)
JOB_ACTIVE = define("E04006", "Cancel the job before deleting its documents.", status=409)
NO_DOCUMENT = define("E04007", "The job has no such document.", status=404)
DEPENDENCY_UNAVAILABLE = define(
    "E04008", "A dependency required to generate the document is unavailable.", status=503
)
STORAGE_UNAVAILABLE = define("E04009", "The generated document could not be stored.", status=502)
INVALID_CONFIG = define("E04010", "The PDF template configuration is invalid.", status=500)
RENDER_FAILED = define("E04011", "The document could not be rendered.", status=500)

# ``PDFError.code`` -> API code. The sync-render and job-lookup errors are
# defined in ``services.jobs``; their codes are spelled out rather than
# imported, so loading this module at startup does not pull in the job
# machinery.
BY_FAILURE_CODE = {
    exceptions.PDFTemplateNotFound.code: TEMPLATE_NOT_FOUND,
    exceptions.PDFRequestDataError.code: INVALID_REQUEST_DATA,
    "PDF_SYNC_RENDER_NOT_ALLOWED": SYNC_RENDER_NOT_ALLOWED,
    "PDF_SYNC_RENDER_TIMEOUT": SYNC_RENDER_TIMEOUT,
    exceptions.PDFJobStateError.code: INVALID_TRANSITION,
    exceptions.PDFDependencyError.code: DEPENDENCY_UNAVAILABLE,
    exceptions.PDFStorageError.code: STORAGE_UNAVAILABLE,
    exceptions.PDFConfigurationError.code: INVALID_CONFIG,
    exceptions.PDFRenderError.code: RENDER_FAILED,
    # A job that is gone (or not the caller's) is the common not-found, the
    # same answer ``get_object()`` gives, so ids cannot be probed.
    "PDF_JOB_NOT_FOUND": api_errors.NOT_FOUND,
}


# API codes that concern one request field rather than the request as a whole.
FIELDS = {INVALID_REQUEST_DATA: "data"}


def api_error(error: exceptions.PDFError) -> BusinessError:
    """Return the API error for a ``PDFError``, keeping its safe message.

    A failure code with no registered counterpart is reported as a server
    error, the status the views have always used for an unmapped code.
    """
    api_code = BY_FAILURE_CODE.get(error.code, api_errors.SERVER_ERROR)
    return BusinessError(api_code, error.safe_message, field=FIELDS.get(api_code))
