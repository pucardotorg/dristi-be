"""eSign transaction lifecycle (spec 0015).

The domain — transaction state machine, APIs, recovery and audit — lives here.
Every ESP-specific wire detail lives behind
:class:`apps.esign.providers.base.ESignProvider`, so nothing in this package
imports ``addon.*``.
"""
