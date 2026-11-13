"""Case lifecycle hooks other modules call (spec 0023 #1.1, #7.5).

The case module owns its stage rules (``case-lifecycle.md``); callers pass
facts, never a stage.
"""

import logging

logger = logging.getLogger(__name__)


def record_hearing_scheduled(case_id, purpose_code, hearing_date):
    """Record that a hearing of the case was scheduled for ``purpose_code``.

    The case module decides whether the purpose starts a stage. Case stages
    are not modelled yet, so this only logs the fact; the stage rules land
    with the case lifecycle and read hearings back through their selectors.
    """
    logger.info(
        "event=CASE_HEARING_SCHEDULED case=%s purpose=%s hearing_date=%s",
        case_id,
        purpose_code,
        hearing_date,
    )
