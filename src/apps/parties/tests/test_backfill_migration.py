"""Tests for the litigant-to-person backfill (spec 0020 §12.2)."""

import importlib

import pytest
from django.apps import apps

from apps.parties.models import Person, VerificationLevel
from apps.parties.tests.factories import make_person
from apps.users.models import Role, User

backfill = importlib.import_module(
    "apps.parties.migrations.0002_backfill_litigant_persons"
).backfill_litigant_persons


def make_user(mobile_number, role, **kwargs):
    """Create a user with a role."""
    return User.objects.create_user(mobile_number=mobile_number, role=role, **kwargs)


@pytest.mark.django_db
class TestBackfillLitigantPersons:
    """One VERIFIED person per litigant, nobody else, safe to re-run."""

    def test_creates_a_verified_person_for_a_litigant(self):
        user = make_user(
            "+919876543210", Role.LITIGANT, name="Priya Sharma", email="priya@example.com"
        )

        backfill(apps, None)

        person = Person.objects.get(user=user)
        assert person.name == "Priya Sharma"
        assert person.phone_number == "+919876543210"
        assert person.email_address == "priya@example.com"
        assert person.verification_level == VerificationLevel.VERIFIED

    def test_missing_email_is_stored_as_null(self):
        user = make_user("+919876543210", Role.LITIGANT, name="Priya")

        backfill(apps, None)

        assert Person.objects.get(user=user).email_address is None

    @pytest.mark.parametrize("role", [Role.ADVOCATE, Role.CLERK, Role.POWER_OF_ATTORNEY, None])
    def test_other_roles_are_skipped(self, role):
        make_user("+919876543210", role, name="Not a litigant")

        backfill(apps, None)

        assert not Person.objects.exists()

    def test_litigant_with_a_person_is_left_alone(self):
        user = make_user("+919876543210", Role.LITIGANT, name="Priya")
        existing = make_person(name="Already linked", user=user)

        backfill(apps, None)

        assert list(Person.objects.filter(user=user)) == [existing]
        assert Person.objects.get(user=user).name == "Already linked"

    def test_running_twice_creates_nothing_new(self):
        make_user("+919876543210", Role.LITIGANT, name="Priya")
        make_user("+919876543211", Role.LITIGANT, name="Rahul")

        backfill(apps, None)
        backfill(apps, None)

        assert Person.objects.count() == 2
