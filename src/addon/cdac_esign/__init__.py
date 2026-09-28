"""C-DAC eSign ESP integration (spec 0015 #7).

Everything about the eSign 2.1 wire protocol lives here: the ``<Esign>``
request, its enveloped XMLDSig signature, the ``<EsignResp>`` parser and the
response verifier. ``apps.esign`` reaches it only through the
``ESIGN_PROVIDER`` setting, so deleting this package plus its settings entries
leaves the domain working on the mock provider.
"""
