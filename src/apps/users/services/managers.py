"""Manager for the mobile-number-keyed user model.

`AbstractBaseUser` ships no manager, and Django's own `UserManager` hardcodes a
`username` argument, so the constructors have to be defined here.
"""

from django.contrib.auth.base_user import BaseUserManager


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
        user.save(using=self._db)
        return user

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
