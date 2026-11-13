"""Signals sent by case writes made during correction (spec 0024 #5.2).

Both are sent inside the write's transaction, so a receiver's work commits or
rolls back with the write; a receiver that raises refuses the write.
"""

from django.dispatch import Signal

# A value of a case in correction changed. ``field_ref`` is the court's field
# ref (``CHQ-3[0]``), or None for a change with no field of its own (an item
# added, removed or changed as a whole); ``section`` is the court's section
# code it belongs to. Sent with ``case_id``, ``field_ref``, ``section``,
# ``old``, ``new`` and ``actor``.
case_field_changed = Signal()

# A document of a case in correction was replaced by a new upload. Sent with
# ``case_id``, ``old_document_id``, ``new_document_id`` (case document ids)
# and ``actor``.
case_document_replaced = Signal()
