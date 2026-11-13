"""Generic demands and payments (spec 0017).

The module owns the financial lifecycle of any payable charge raised by another
Dristi module: what is owed (``Demand`` / ``DemandItem``), what was collected
(``Payment`` / ``PaymentDemandItem``) and the provider contract a payment
gateway addon implements. It never decides what a fee is or what happens once
it is paid.
"""
