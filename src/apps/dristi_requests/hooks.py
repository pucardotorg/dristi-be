"""Post-approval hook registry.

This is the integration point between the generic request engine and the
apps that use it. This app owns the *workflow*; the consuming app
owns the *meaning* of a request type and any side effect of approving it.

A consuming app registers a hook for its request type code and applies the
side effect to its own models::

    # apps/users/hooks.py
    from apps.dristi_requests.hooks import register_hook


    @register_hook("LAWYER_BAR_UPDATE")
    def apply_bar_update(request):
        profile = request.requester.profile
        profile.bar_number = request.data["bar_number"]
        profile.bar_id_status = profile.BarIdStatus.VERIFIED
        # Persist the file_id (spec 0014), not the RequestDocument row.
        profile.bar_certificate_file_id = request.documents.first().file_id
        profile.save()

Register hooks at import time and import the module from the owning app's
``AppConfig.ready()`` so registration happens exactly once::

    # apps/users/apps.py
    def ready(self):
        from . import hooks  # noqa: F401

Contract for hook authors:

- The hook receives the approved ``Request``. Everything it needs is on it:
  ``requester``, ``data`` (schema-validated at submit time), ``documents``
  (``RequestDocument`` rows, in upload order) and ``request_type``.
- Documents are stored by ``apps.files``. Keep a reference to one by its
  ``file_id`` (``document.file_id``); read its content in-process with
  ``apps.files.services.get_file_content(file_id)``. Never call
  ``delete_file`` on it: the request still references it, and the foreign
  key is ``PROTECT`` so the attempt fails.
- The hook runs inside the same transaction as the approving decision, so
  raising rolls the decision back and leaves the approval pending. Keep
  hooks idempotent: a request can be rejected and resubmitted.
- A request type without a hook is valid; approval then only changes the
  request's own status.

Rejection hooks
---------------

A consuming app that keeps its own record of the outcome (a profile's
approval status, say) also needs to hear about a rejection. Register for it
with ``on=RequestApproval.Status.REJECTED``; the hook receives the request and the
deciding ``RequestApproval``, whose ``comments`` carry the approver's reason::

    @register_hook("ADVOCATE_REGISTRATION", on=RequestApproval.Status.REJECTED)
    def reject_registration(request, approval):
        ...

The same contract applies: it runs in the rejecting transaction, raising
rolls the rejection back, and it must be idempotent, since a resubmitted
request can be rejected again.
"""

import logging

from .models import RequestApproval

logger = logging.getLogger(__name__)

POST_APPROVAL_HOOKS = {}
REJECTION_HOOKS = {}

# A hook fires on an approver's decision, so the events are the decisions.
_REGISTRIES = {
    RequestApproval.Status.APPROVED: POST_APPROVAL_HOOKS,
    RequestApproval.Status.REJECTED: REJECTION_HOOKS,
}


def register_hook(request_type_code, on=RequestApproval.Status.APPROVED):
    """Register a hook for a request type code, run on approval or rejection."""
    if on not in _REGISTRIES:
        raise ValueError(f"Unknown hook event {on!r}; expected one of {', '.join(_REGISTRIES)}.")
    registry = _REGISTRIES[on]

    def decorator(fn):
        registry[request_type_code] = fn
        return fn

    return decorator


def get_hook(request_type_code, on=RequestApproval.Status.APPROVED):
    """Return the hook registered for a request type code and event, if any."""
    return _REGISTRIES[on].get(request_type_code)


def run_post_approval_hooks(request):
    """Run the hook registered for the request's type, if one exists."""
    _run_hook(RequestApproval.Status.APPROVED, request)


def run_rejection_hooks(request, approval):
    """Run the rejection hook registered for the request's type, if one exists."""
    _run_hook(RequestApproval.Status.REJECTED, request, approval)


def _run_hook(on, request, *args):
    """Run the ``on`` hook registered for the request's type, if one exists."""
    code = request.request_type.code
    hook = get_hook(code, on=on)
    if hook:
        logger.info("Running %s hook for request %s (%s)", on, request.pk, code)
        hook(request, *args)
