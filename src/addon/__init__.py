"""Pluggable third-party integrations.

Each subpackage is an independently installable integration that depends on
``apps.*`` but is never imported by it. Integrations are activated purely
through settings (for example ``MESSAGING_BACKENDS``), so deleting a subpackage
plus its settings entries leaves the core apps working.
"""
