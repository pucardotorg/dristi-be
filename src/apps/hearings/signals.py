"""Signals other modules subscribe to (spec 0023 #11.6).

Each is sent on commit with ``hearing_id`` and ``case_id``. A subscriber reads
the hearing back through ``apps.hearings.selectors``, never from the payload
alone.
"""

from django.dispatch import Signal

# Confirm of a new date.
hearing_scheduled = Signal()
# Any move; also carries ``from_date`` and ``to_date``.
hearing_rescheduled = Signal()
# End, and abandonment by the midnight sweep; also carries ``abandoned``.
hearing_ended = Signal()
# Cancel; also carries ``reason``.
hearing_cancelled = Signal()
