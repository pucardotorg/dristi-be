"""Offline payment provider (spec 0032).

Money handed over in person — cash, a demand draft or a card/UPI swipe at a
court counter — and recorded in Dristi by court staff. Only what is specific to
that channel lives here: the payment request reference, the instructions shown
to the payer, the validity window and the validation of what staff record.
``apps.payments`` reaches it only through the ``PAYMENT_PROVIDERS`` setting, so
deleting this package plus its settings entries leaves the payments module
working on the other providers.
"""
