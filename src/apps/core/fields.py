"""Custom DRF fields shared across apps."""

from rest_framework import serializers
from rest_framework.fields import empty


class StrictBooleanField(serializers.BooleanField):
    """BooleanField that accepts only the literal "true"/"false" (case-insensitive).

    DRF's own BooleanField also accepts "1"/"0"/"yes"/"on"/etc, which is more
    permissive than this API's query-param contract wants.
    """

    default_error_messages = {
        "invalid": 'Must be "true" or "false".',
    }

    default_empty_html = empty

    def to_internal_value(self, data):
        """Normalize to lowercase and accept only "true"/"false"."""
        if isinstance(data, str):
            data = data.strip().lower()
        if data == "true":
            return True
        if data == "false":
            return False
        self.fail("invalid", input=data)
