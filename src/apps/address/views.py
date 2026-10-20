"""Address API views."""

import re

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PINCODE_REGEX
from .serializers import PincodeDetailsSerializer
from .services import PincodeNotFoundError, PincodeServiceUnavailableError, lookup_pincode

ERROR_RESPONSE = inline_serializer(
    name="PincodeLookupError",
    fields={"detail": serializers.CharField(), "code": serializers.CharField()},
)


class PincodeLookupError(APIException):
    """A pincode lookup failure, with a stable ``code`` the frontend can branch on.

    The body is ``{"detail": ..., "code": ...}``: DRF renders a dict ``detail``
    as is, so the code reaches the client alongside the message.
    """

    def __init__(self):
        super().__init__(detail={"detail": self.default_detail, "code": self.default_code})


class InvalidPincode(PincodeLookupError):  # noqa: N818 - named after its code
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Enter a valid 6-digit pincode not starting with 0."
    default_code = "invalid_pincode"


class PincodeNotFound(PincodeLookupError):  # noqa: N818
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "No district or state is recorded for this pincode."
    default_code = "pincode_not_found"


class PincodeServiceUnavailable(PincodeLookupError):  # noqa: N818
    """India Post is down: the frontend should let the user type district and state."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The pincode lookup service is unavailable. Enter district and state manually."
    default_code = "pincode_service_unavailable"


class PincodeLookupView(APIView):
    """GET /pincodes/<pincode>/ — district and state to pre-fill an address form."""

    @extend_schema(
        tags=["address"],
        responses={
            200: PincodeDetailsSerializer,
            400: OpenApiResponse(
                ERROR_RESPONSE, description=f"code = {InvalidPincode.default_code}"
            ),
            404: OpenApiResponse(
                ERROR_RESPONSE, description=f"code = {PincodeNotFound.default_code}"
            ),
            503: OpenApiResponse(
                ERROR_RESPONSE,
                description=(
                    f"code = {PincodeServiceUnavailable.default_code}; the India Post API "
                    "is down, so district and state must be entered manually."
                ),
            ),
        },
    )
    def get(self, request, pincode):
        """Look the pincode up with India Post."""
        if not re.fullmatch(PINCODE_REGEX, pincode):
            raise InvalidPincode
        try:
            details = lookup_pincode(pincode)
        except PincodeNotFoundError as exc:
            raise PincodeNotFound from exc
        except PincodeServiceUnavailableError as exc:
            raise PincodeServiceUnavailable from exc
        return Response(PincodeDetailsSerializer(details).data)
