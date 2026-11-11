"""Bounded values of the hearings module (spec 0023)."""

from django.db import models


class CalendarEntryType(models.TextChoices):
    """Why a court's day differs from a normal sitting day (#2.5).

    Only ``REDUCED_SITTING`` is a sitting day; every other type is not (#4).
    """

    HOLIDAY = "HOLIDAY", "Holiday"
    PRESIDING_OFFICER_LEAVE = "PRESIDING_OFFICER_LEAVE", "Presiding officer on leave"
    NON_SITTING = "NON_SITTING", "Non-sitting day"
    REDUCED_SITTING = "REDUCED_SITTING", "Reduced sitting"
