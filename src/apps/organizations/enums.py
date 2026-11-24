"""Enums for organizations and court access (spec 0029)."""

from django.db import models


class CourtLevel(models.TextChoices):
    """The part an organization plays in the court hierarchy (spec 0029 #2).

    Null on any other organization (a High Court, a district court as an
    administrative unit): it holds no court access.
    """

    ESTABLISHMENT = "ESTABLISHMENT", "Court establishment"
    COURTROOM = "COURTROOM", "Courtroom"
