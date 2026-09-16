"""Post-approval hook registry.

Each request type registers its own hook, so adding a type never requires
editing the core approval engine.
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
