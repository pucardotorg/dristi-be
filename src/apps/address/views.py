"""Address API views."""

import re

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.errors import BusinessError
from apps.api.schema import error_responses

from . import errors
from .models import PINCODE_REGEX
from .serializers import PincodeDetailsSerializer
from .services import PincodeNotFoundError, PincodeServiceUnavailableError, lookup_pincode


class PincodeLookupView(APIView):
    """GET /pincodes/<pincode>/ — district and state to pre-fill an address form."""

    @extend_schema(
        responses={
            200: PincodeDetailsSerializer,
            **error_responses(
                errors.INVALID_PINCODE,
                errors.PINCODE_NOT_FOUND,
                errors.PINCODE_SERVICE_UNAVAILABLE,
            ),
        },
    )
    def get(self, request, pincode):
        """Look the pincode up with India Post.

        When India Post is down (``E05003``) district and state must be
        entered manually.
        """
        if not re.fullmatch(PINCODE_REGEX, pincode):
            raise BusinessError(errors.INVALID_PINCODE)
        try:
            details = lookup_pincode(pincode)
        except PincodeNotFoundError as exc:
            raise BusinessError(errors.PINCODE_NOT_FOUND) from exc
        except PincodeServiceUnavailableError as exc:
            raise BusinessError(errors.PINCODE_SERVICE_UNAVAILABLE) from exc
        return Response(PincodeDetailsSerializer(details).data)
