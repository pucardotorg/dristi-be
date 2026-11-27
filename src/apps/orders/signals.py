"""Signals other modules subscribe to (spec 0039 #9.5).

Each is sent on commit with ``order_id`` and ``case_id`` only. A subscriber reads
the order back through ``apps.orders.selectors``, never from the payload alone.
"""

from django.dispatch import Signal

# A signature was recorded.
order_signed = Signal()
# The order is signed and its order data complete: its workflows go out.
order_triggered = Signal()
# A diary entry was edited after triggering (#6.6).
diary_entry_changed = Signal()
# Gujarat: the Roznama of a normal order was signed (#8.4).
roznama_signed = Signal()
