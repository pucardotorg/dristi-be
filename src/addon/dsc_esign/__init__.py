"""DSC token signing integration (spec 0038).

A ``CLIENT_SIGNATURE`` provider: the signer's own DSC token (on a local agent)
produces a detached PKCS#7 over the ByteRange digest the backend prepared, and
this addon verifies that signature against the document and the certificate
policy before ``apps.esign`` embeds it. Everything DSC-specific — the local-agent
payload and the certificate checks — stays here; ``apps.esign`` reaches it only
through the ``ESIGN_PROVIDERS`` registry, so deleting this package plus its
settings leaves the domain working on its other providers.
"""
