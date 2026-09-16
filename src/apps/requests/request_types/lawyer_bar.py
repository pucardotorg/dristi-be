"""LAWYER_BAR_UPDATE request type.

Created purely through configuration: a ``RequestType`` row (see the data
migration), the schema below, and the post-approval hook registered here.
No dedicated endpoint is needed — it is submitted through the generic
create endpoint.
"""

from ..hooks import register_hook
from ..models import LawyerBarDocument, LawyerProfile

REQUEST_TYPE_CODE = "LAWYER_BAR_UPDATE"

LAWYER_BAR_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["name", "bar_number"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "bar_number": {"type": "string", "minLength": 1},
    },
}

MIN_DOCUMENTS = 1

APPROVER_ROLE = "BAR_COUNCIL_APPROVER"


def resolve_person_for_requester(requester):
    """Return (creating if needed) the lawyer profile of the requester."""
    person, _ = LawyerProfile.objects.get_or_create(user=requester)
    return person


@register_hook(REQUEST_TYPE_CODE)
def apply_bar_update(request):
    """Apply the approved bar details to the requester's lawyer profile."""
    person = resolve_person_for_requester(request.requester)
    person.name = request.data["name"]
    person.bar_number = request.data["bar_number"]
    person.save(update_fields=["name", "bar_number", "updated_at"])

    doc = request.documents.first()
    LawyerBarDocument.objects.create(person=person, request_document=doc)
    return person
