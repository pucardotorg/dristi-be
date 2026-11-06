"""e-GRAS payment gateway integration (spec 0022).

Everything about the e-GRAS wire protocol lives here: the e-Challan redirect
form, the untrusted return-URL callback, the SOAP GRN status lookup and the
status vocabulary. ``apps.payments`` reaches it only through the
``PAYMENT_PROVIDERS`` setting, so deleting this package plus its settings
entries leaves the payments module working on the mock provider.
"""
