"""Bounded values of the scrutiny module (spec 0024 #3)."""

from django.db import models


class Decision(models.TextChoices):
    """A decision scrutiny delegates to a business rule bound per jurisdiction (#2.4)."""

    CHECKS = "CHECKS", "Advisory checks"
