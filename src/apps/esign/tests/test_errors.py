"""eSign failure codes map onto registered API error codes (spec 0000 #9, spec 0015 #10)."""

from django.test import SimpleTestCase
from rest_framework import status

from apps.api import errors as api_errors
from apps.esign import constants, errors
from apps.esign.exceptions import ESignError, ESignNotPermitted
from apps.esign.views import ERROR_STATUS

FAILURE_CODES = sorted(
    value
    for name, value in vars(constants).items()
    if name.startswith("ESIGN_") and isinstance(value, str)
)


class FailureCodeMappingTests(SimpleTestCase):
    """Every failure an endpoint can report has one registered API code."""

    def test_every_failure_code_has_an_api_code(self):
        self.assertEqual(sorted(errors.BY_FAILURE_CODE), FAILURE_CODES)

    def test_api_codes_are_distinct(self):
        codes = [error.code for error in errors.BY_FAILURE_CODE.values()]
        self.assertEqual(len(codes), len(set(codes)))

    def test_status_is_the_one_the_views_always_returned(self):
        """Unlisted failure codes were always a 500 from the JSON endpoints."""
        for failure_code, error in errors.BY_FAILURE_CODE.items():
            with self.subTest(failure_code):
                self.assertEqual(
                    error.status,
                    ERROR_STATUS.get(failure_code, status.HTTP_500_INTERNAL_SERVER_ERROR),
                )


class ApiErrorTests(SimpleTestCase):
    """``api_error`` turns an ``ESignError`` into the standard error."""

    def test_keeps_the_user_safe_message(self):
        exc = errors.api_error(ESignNotPermitted("You cannot sign this order."))
        self.assertEqual(exc.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            api_errors.error_items(exc),
            [{"code": errors.NOT_PERMITTED.code, "message": "You cannot sign this order."}],
        )

    def test_unregistered_failure_code_is_a_server_error(self):
        exc = errors.api_error(ESignError("Something broke.", code="ESIGN_FUTURE_CODE"))
        self.assertEqual(exc.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        [item] = api_errors.error_items(exc)
        self.assertEqual(item["code"], api_errors.SERVER_ERROR.code)
