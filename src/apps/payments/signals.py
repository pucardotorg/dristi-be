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

TODO(demand-origin): never identify "your" demand by ``reference_type`` /
``reference_id`` (or an item's). Any user can raise a demand over REST
(``POST /payments/demands/``) with whatever references and amounts they like,
e.g. a 0.01 ``CASE_FILING`` demand for their own filing; a receiver matching on
references would treat paying it as paying the real filing fee. Harmless while
no receiver exists. Before the first one is written, decide how demands raised
over REST are told apart from those raised in-process (match on the stored id
only, add a server-set ``raised_via`` field, or restrict REST creation) and
record the decision in spec 0017 #14.
"""

from django.dispatch import Signal

# kwargs: payment (Payment), demand (Demand), items (list[DemandItem] this payment
# paid), demand_paid (bool: the demand is now fully PAID).
payment_completed = Signal()
