"""Signals other modules subscribe to (spec 0028 #10.2).

``process_status_changed`` is sent on commit with ``process_id``, ``case_id``,
``from_status`` and ``to_status``. A receiver reads the process back through
``apps.processes.selectors``.
"""

from django.dispatch import Signal

process_status_changed = Signal()
