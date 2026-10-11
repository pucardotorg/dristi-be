"""Address API views."""

import re

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PINCODE_REGEX
from .services import PincodeNotFoundError, PincodeServiceUnavailableError, lookup_pincode

# Each failure carries a stable ``code`` the frontend can branch on; on
# ``pincode_service_unavailable`` it should let the user type district and
# state by hand.
INVALID_PINCODE = "invalid_pincode"
PINCODE_NOT_FOUND = "pincode_not_found"
PINCODE_SERVICE_UNAVAILABLE = "pincode_service_unavailable"

ERROR_RESPONSE = inline_serializer(
    name="PincodeLookupError",
    fields={"detail": serializers.CharField(), "code": serializers.CharField()},
)


class PincodeDetailsSerializer(serializers.Serializer):
    """District and state for a pincode."""

    pincode = serializers.CharField()
    district = serializers.CharField()
    state = serializers.CharField()


class PincodeLookupView(APIView):
    """GET /pincodes/<pincode>/ — district and state to pre-fill an address form."""

    @extend_schema(
        tags=["address"],
        responses={
            200: PincodeDetailsSerializer,
            400: OpenApiResponse(ERROR_RESPONSE, description=f"code = {INVALID_PINCODE}"),
            404: OpenApiResponse(ERROR_RESPONSE, description=f"code = {PINCODE_NOT_FOUND}"),
            503: OpenApiResponse(
                ERROR_RESPONSE,
                description=(
                    f"code = {PINCODE_SERVICE_UNAVAILABLE}; the India Post API is down, "
                    "so district and state must be entered manually."
                ),
            ),
        },
    )
    def get(self, request, pincode):
        """Look the pincode up with India Post."""
        if not re.fullmatch(PINCODE_REGEX, pincode):
            return _error(
                status.HTTP_400_BAD_REQUEST,
                INVALID_PINCODE,
                "Enter a valid 6-digit pincode not starting with 0.",
            )

        try:
            details = lookup_pincode(pincode)
        except PincodeNotFoundError:
            return _error(
                status.HTTP_404_NOT_FOUND,
                PINCODE_NOT_FOUND,
                "No district or state is recorded for this pincode.",
            )
        except PincodeServiceUnavailableError:
            return _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                PINCODE_SERVICE_UNAVAILABLE,
                "The pincode lookup service is unavailable. Enter district and state manually.",
            )

        return Response(PincodeDetailsSerializer(details).data)


def _error(status_code, code, detail):
    """Return an error body with a machine-readable ``code``."""
    return Response({"detail": detail, "code": code}, status=status_code)
