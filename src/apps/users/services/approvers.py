"""Make system admins bar-ID approvers on local and test setups (issue #260).

Every registration and bar-ID request routes its approval step to the
``BAR_ID_APPROVER`` group, and routing fails while that group has no member
other than the requester. Migrations create the group but add nobody to it, so
a fresh stack could not create a request until someone added a member by hand.

Every superuser is therefore added to the group, both when migrations run
(superusers that already exist) and when a superuser is created. Superusers are
picked by ``is_superuser``, so no environment needs a mobile number configured.

Off in production (``SEED_SUPERUSER_APPROVERS``): routing assigns the first
eligible member by mobile number, so a superuser in the group could take
requests meant for the real approvers.
"""

import logging

from django.apps import apps as global_apps
from django.conf import settings

logger = logging.getLogger(__name__)

# The same name the request-type seed migrations give the group; they keep their
# own copy, as migrations must not import application code.
BAR_ID_APPROVER = "BAR_ID_APPROVER"


def enabled():
    """Whether superusers are made bar-ID approvers in this environment."""
    return getattr(settings, "SEED_SUPERUSER_APPROVERS", False)


def add_to_bar_id_approvers(users, *, group_model, using="default"):
    """Add ``users`` to ``BAR_ID_APPROVER``, creating the group if it is missing.

    Idempotent: a user already in the group is left as it is. Returns how many
    users were newly added.
    """
    group, _ = group_model.objects.using(using).get_or_create(name=BAR_ID_APPROVER)
    members = group.user_set.db_manager(using)
    existing = set(members.values_list("pk", flat=True))
    new = [user for user in users if user.pk not in existing]
    if new:
        members.add(*new)
    return len(new)


def add_superusers_to_bar_id_approvers(*, user_model, group_model, using="default"):
    """Add every superuser to ``BAR_ID_APPROVER``; returns how many were newly added.

    Takes the models as arguments so a ``post_migrate`` receiver can pass the
    historical ones.
    """
    superusers = user_model._default_manager.db_manager(using).filter(is_superuser=True)
    added = add_to_bar_id_approvers(superusers, group_model=group_model, using=using)
    if added:
        logger.info("event=SUPERUSER_APPROVERS_SEEDED group=%s added=%d", BAR_ID_APPROVER, added)
    return added


def seed_superuser_approvers(sender, *, apps=global_apps, using="default", **kwargs):
    """``post_migrate`` receiver: make the superusers that already exist approvers.

    Uses the migration state's models, the way ``django.contrib.auth`` creates
    permissions, and does nothing when the user or group table is not in that
    state (for example after ``migrate users zero``). ``flush`` sends the signal
    without ``apps``, so it defaults to the installed models.
    """
    if not enabled():
        return
    try:
        user_model = apps.get_model(settings.AUTH_USER_MODEL)
        group_model = apps.get_model("auth", "Group")
    except LookupError:
        return
    add_superusers_to_bar_id_approvers(user_model=user_model, group_model=group_model, using=using)
