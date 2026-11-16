"""Manager for the mobile-number-keyed user model.

`AbstractBaseUser` ships no manager, and Django's own `UserManager` hardcodes a
`username` argument, so the constructors have to be defined here.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import BaseUserManager
from django.db import transaction


class UserManager(BaseUserManager):
    """Creates accounts keyed by `mobile_number`."""

    use_in_migrations = True

    def _create_user(self, mobile_number, password=None, **extra_fields):
        if not mobile_number:
            raise ValueError("A mobile number is required.")

        email = extra_fields.pop("email", None)
        user = self.model(
            mobile_number=mobile_number,
            email=self.normalize_email(email) if email else None,
            **extra_fields,
        )
        # set_password(None) marks the password unusable, which is the correct
        # state for an account created from an OTP before the wizard finishes.
        user.set_password(password)
        with transaction.atomic(using=self._db):
            user.save(using=self._db)
            self._make_approver_if_superuser(user)
        return user

    def _make_approver_if_superuser(self, user):
        """Add a new superuser to BAR_ID_APPROVER where that is enabled (issue #260).

        Covers ``create_user(is_superuser=True)`` too, not only
        ``create_superuser``. Skipped for the historical model a migration
        hands this manager, which cannot mix with the real ``Group``.
        """
        from django.contrib.auth.models import Group

        from . import approvers

        if not user.is_superuser or not approvers.enabled():
            return
        if self.model is not get_user_model():
            return
        approvers.add_to_bar_id_approvers([user], group_model=Group, using=self._db or "default")

    def create_user(self, mobile_number, password=None, **extra_fields):
        """Create a regular account."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(mobile_number, password, **extra_fields)

    def create_superuser(self, mobile_number, password=None, **extra_fields):
        """Create an admin account, already past the registration wizard."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        # Literal rather than the enum: importing models here would be circular.
        extra_fields.setdefault("registration_status", "COMPLETE")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")

        return self._create_user(mobile_number, password, **extra_fields)
