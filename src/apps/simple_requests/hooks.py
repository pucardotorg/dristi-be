"""Post-approval hook registry.

This is the integration point between the generic request engine and the
apps that use it. This app owns the *workflow*; the consuming app
owns the *meaning* of a request type and any side effect of approving it.

A consuming app registers a hook for its request type code and applies the
side effect to its own models::

    # apps/users/hooks.py
    from apps.simple_requests.hooks import register_hook


    @register_hook("LAWYER_BAR_UPDATE")
    def apply_bar_update(request):
        profile = request.requester.profile
        profile.bar_number = request.data["bar_number"]
        profile.bar_id_status = profile.BarIdStatus.VERIFIED
        profile.bar_certificate = request.documents.first()  # a RequestDocument
        profile.save()

Register hooks at import time and import the module from the owning app's
``AppConfig.ready()`` so registration happens exactly once::

    # apps/users/apps.py
    def ready(self):
        from . import hooks  # noqa: F401

Contract for hook authors:

- The hook receives the approved ``Request``. Everything it needs is on it:
  ``requester``, ``data`` (schema-validated at submit time), ``documents``
  (``RequestDocument`` rows) and ``request_type``.
- The hook runs inside the same transaction as the approving decision, so
  raising rolls the decision back and leaves the approval pending. Keep
  hooks idempotent: a request can be rejected and resubmitted.
- A request type without a hook is valid; approval then only changes the
  request's own status.
"""

import logging

logger = logging.getLogger(__name__)

POST_APPROVAL_HOOKS = {}


def register_hook(request_type_code):
    """Register a post-approval hook for a request type code."""

    def decorator(fn):
        POST_APPROVAL_HOOKS[request_type_code] = fn
        return fn

    return decorator


def get_hook(request_type_code):
    """Return the hook registered for a request type code, if any."""
    return POST_APPROVAL_HOOKS.get(request_type_code)


def run_post_approval_hooks(request):
    """Run the hook registered for the request's type, if one exists."""
    hook = POST_APPROVAL_HOOKS.get(request.request_type.code)
    if hook:
        logger.info(
            "Running post-approval hook for request %s (%s)",
            request.pk,
            request.request_type.code,
        )
        hook(request)
