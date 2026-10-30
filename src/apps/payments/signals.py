"""How raising modules hear that money is in (spec 0017 #14, open question 7).

A plain Django signal, sent by the ``notify_payment_completed`` actor once per
successful payment, keeps this module free of any import of the modules that
raise demands. A receiver registers in its own app and reacts only to demands
it raised itself, identified by the demand (or item) id it stored when it
called ``DemandService.raise_demand``::

    @receiver(payment_completed)
    def on_paid(sender, payment, demand, items, demand_paid, **kwargs):
        filing = CaseFiling.objects.filter(demand_id=demand.pk).first()
        if filing is not None and demand_paid:
            ...

Receivers must be idempotent: a message can be delivered more than once. Only
``SUCCESS`` is ever announced; ``PENDING`` is never paid.

Every demand is raised in-process (there is no REST create, spec 0017
"Implementation notes"), so a receiver can trust that a demand it stored the id
of is its own. Still match on that id, never on ``reference_type`` /
``reference_id``: references are free text, and if REST creation ever returns
(see the spec note), a caller could reuse them on a demand of its own.
"""

from django.dispatch import Signal

# kwargs: payment (Payment), demand (Demand), items (list[DemandItem] this payment
# paid), demand_paid (bool: the demand is now fully PAID).
payment_completed = Signal()
