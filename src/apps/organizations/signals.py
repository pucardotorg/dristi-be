"""Court access change notification (spec 0029 #8.3).

``court_access_changed`` is sent after commit whenever who may do what at a
court changes, with:

* ``organization_ids``: the establishments and courtrooms affected;
* ``actions``: the action codes added or removed, or ``None`` when the change
  is to a courtroom list (who reads, not who acts) or to whole assignments.

Case workflows (spec 0011) subscribe to refresh their task users. Until they
exist, nothing listens.
"""

from django.db import transaction
from django.dispatch import Signal

court_access_changed = Signal()


def send_after_commit(organization_ids, actions=None):
    """Send ``court_access_changed`` once the current transaction commits (never on rollback)."""
    organization_ids = sorted({str(pk) for pk in organization_ids if pk is not None})
    if not organization_ids:
        return
    actions = sorted(set(actions)) if actions is not None else None

    def send():
        court_access_changed.send(
            sender=court_access_changed, organization_ids=organization_ids, actions=actions
        )

    transaction.on_commit(send)
