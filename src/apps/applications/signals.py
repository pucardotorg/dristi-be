"""Signals other modules subscribe to (spec 0033 #16.4).

Sent on commit with ids only; receivers read the application back through
``apps.applications.selectors``.
"""

from django.dispatch import Signal

# Every status change: ``application_id``, ``case_id``, ``from_status``, ``to_status``, ``action``.
application_status_changed = Signal()
# A Bail application accepted (#12.2): ``application_id``, ``case_id``, ``order_id``.
bail_bond_requested = Signal()
