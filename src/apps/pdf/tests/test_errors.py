"""PDF failure codes map onto registered API error codes (spec 0000 #9)."""

from django.test import SimpleTestCase
from rest_framework import status

from apps.api import errors as api_errors
from apps.pdf import errors, exceptions
from apps.pdf.services import jobs


def _api_failure_codes():
    """``PDFError`` codes the endpoints can raise.

    The signing primitives (#14.3) are used by eSign, which maps them to its
    own codes; they never reach a PDF endpoint.
    """
    classes = [
        value
        for value in [*vars(exceptions).values(), *vars(jobs).values()]
        if isinstance(value, type)
        and issubclass(value, exceptions.PDFError)
        and value is not exceptions.PDFError
        and not issubclass(value, exceptions.PDFSigningError)
    ]
    return sorted({cls.code for cls in classes})


class FailureCodeMappingTests(SimpleTestCase):
    """Every failure an endpoint can report has one registered API code."""

    def test_every_failure_code_has_an_api_code(self):
        self.assertEqual(sorted(errors.BY_FAILURE_CODE), _api_failure_codes())

    def test_api_codes_are_distinct(self):
        codes = [error.code for error in errors.BY_FAILURE_CODE.values()]
        self.assertEqual(len(codes), len(set(codes)))


class ApiErrorTests(SimpleTestCase):
    """``api_error`` turns a ``PDFError`` into the standard error."""

    def test_keeps_the_safe_message(self):
        exc = errors.api_error(exceptions.PDFJobStateError("A COMPLETED job cannot be cancelled."))
        self.assertEqual(exc.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            api_errors.error_items(exc),
            [
                {
                    "code": errors.INVALID_TRANSITION.code,
                    "message": "A COMPLETED job cannot be cancelled.",
                }
            ],
        )

    def test_missing_job_is_the_common_not_found(self):
        exc = errors.api_error(jobs.PDFJobNotFound())
        self.assertEqual(exc.status_code, status.HTTP_404_NOT_FOUND)
        [item] = api_errors.error_items(exc)
        self.assertEqual(item["code"], api_errors.NOT_FOUND.code)

    def test_unregistered_failure_code_is_a_server_error(self):
        exc = errors.api_error(exceptions.PDFNotParsable())
        self.assertEqual(exc.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        [item] = api_errors.error_items(exc)
        self.assertEqual(item["code"], api_errors.SERVER_ERROR.code)
