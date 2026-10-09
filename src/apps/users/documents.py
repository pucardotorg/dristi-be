"""Documents submitted with a registration.

A registration document is stored through ``apps.files`` and linked to the
registrant by ``File.user``. Which document it is (the bar council ID, say)
is recorded as a file tag, so the tag constants here are the only place that
name is spelled. Which formats are accepted is ``apps.files.documents``'s to say.
"""

from rest_framework import serializers

from apps.files.documents import document_error

BAR_COUNCIL_ID_TAG = "bar-council-id"


def validate_registration_document(upload):
    """Reject an upload that is not an accepted document, as a 400 on the field.

    Checked before anything is written, so a bad file never reaches Object
    Storage.
    """
    error = document_error(upload)
    if error:
        raise serializers.ValidationError(error[0].upper() + error[1:])
    return upload
