"""E-filing switches read from the public configuration store (spec 0034).

Read at the point of use, so an admin edit applies to the next request. The
same rows are served to the frontend by ``GET /public-configuration/ui_efiling``.
"""

from apps.core import services as config

EFILING_UI_CONFIG_SET = "ui_efiling"
NATIVELY_DIGITAL_KEY = "natively_digital_document_submission_on"


def natively_digital_on() -> bool:
    """Whether documents carry the natively digital attribute in this state.

    When off, the e-filing UI does not ask for it and the complaint PDF's list
    of documents has no Natively Digital column. A missing or inactive row
    counts as off, so a new state does not see the question by accident.
    """
    return config.get_public_bool(EFILING_UI_CONFIG_SET, NATIVELY_DIGITAL_KEY, default=False)
