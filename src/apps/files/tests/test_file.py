"""Tests for the File and FileTag models."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.files.models import File, FileTag
from apps.files.tests.factories import make_file, make_tag, make_user
from apps.organizations.tests.factories import make_organization


@pytest.mark.django_db
class TestFileTagNormalization:
    """Tag names are slugified so equivalent inputs collapse to one row."""

    @pytest.mark.parametrize("name", ["identity", "Identity", "IDENTITY", "  identity  "])
    def test_case_and_whitespace_variants_produce_the_same_slug(self, name):
        assert make_tag(name).name == "identity"

    def test_spaces_are_slugified_to_hyphens(self):
        assert make_tag("Address Proof").name == "address-proof"

    def test_equivalent_names_collide_on_the_unique_constraint(self):
        make_tag("identity")
        with pytest.raises(ValidationError):
            make_tag("IDENTITY")

    def test_tag_reuse_across_files(self):
        tag = make_tag("verification")
        first = make_file(tags=[tag])
        second = make_file(tags=[tag])

        assert FileTag.objects.count() == 1
        assert tag.files.count() == 2
        assert set(tag.files.all()) == {first, second}

    def test_str_returns_name(self):
        assert str(make_tag("Address Proof")) == "address-proof"

    def test_ordering_is_alphabetical(self):
        make_tag("verification")
        make_tag("address-proof")
        make_tag("identity")

        assert list(FileTag.objects.values_list("name", flat=True)) == [
            "address-proof",
            "identity",
            "verification",
        ]


@pytest.mark.django_db
class TestFileTagValidation:
    """Names that cannot be slugified without losing meaning are rejected."""

    @pytest.mark.parametrize("name", ["", "   ", "!!!"])
    def test_names_without_alphanumerics_are_rejected(self, name):
        with pytest.raises(ValidationError):
            make_tag(name)

    @pytest.mark.parametrize("name", ["नीति", "കേരളം", "café-proof"])
    def test_non_ascii_names_are_rejected(self, name):
        with pytest.raises(ValidationError):
            make_tag(name)

    def test_mixed_script_name_is_rejected_rather_than_silently_truncated(self):
        """slugify() would drop the non-ASCII part and keep "invoice"."""
        with pytest.raises(ValidationError):
            make_tag("नीति-invoice")

        assert not FileTag.objects.filter(name="invoice").exists()

    def test_name_longer_than_max_length_is_rejected(self):
        with pytest.raises(ValidationError):
            make_tag("a" * 101)


@pytest.mark.django_db
class TestFileModel:
    """Field behaviour and defaults on File."""

    def test_str_includes_file_name_and_id(self):
        file = make_file(file_name="a.pdf")
        assert str(file) == f"a.pdf ({file.id})"

    def test_is_active_defaults_to_true(self):
        file = make_file()

        assert file.is_active is True
        assert File.objects.active().count() == 1

    def test_ordering_is_newest_first(self):
        first = make_file(file_name="first.pdf")
        second = make_file(file_name="second.pdf")

        assert list(File.objects.all()) == [second, first]

    def test_organization_is_optional(self):
        file = make_file()
        assert file.organization_id is None

    def test_organization_can_be_assigned(self):
        org = make_organization(code="FILES_ORG")
        file = make_file(organization=org)

        assert file.organization_id == org.id
        assert org.files.count() == 1

    def test_user_is_recorded_and_reverse_accessible(self):
        user = make_user()
        file = make_file(user=user)

        assert file.user_id == user.id
        assert user.uploaded_files.count() == 1

    def test_storage_path_must_be_unique(self):
        make_file(storage_path="files/2026/09/duplicate.pdf")
        with pytest.raises(IntegrityError):
            make_file(storage_path="files/2026/09/duplicate.pdf")

    def test_unknown_file_type_is_rejected_by_full_clean(self):
        """File does not self-validate on save; the service layer calls full_clean()."""
        file = make_file()
        file.file_type = "not_a_real_type"

        with pytest.raises(ValidationError):
            file.full_clean()


@pytest.mark.django_db
class TestFileDeletionRules:
    """PROTECT policies and tag lifecycle."""

    def test_organization_is_protected_while_it_has_files(self):
        org = make_organization(code="PROTECTED_ORG")
        make_file(organization=org)

        with pytest.raises(ProtectedError):
            org.delete()

    def test_user_is_protected_while_they_have_uploaded_files(self):
        user = make_user()
        make_file(user=user)

        with pytest.raises(ProtectedError):
            user.delete()

    def test_deleting_a_file_keeps_the_tags(self):
        shared = make_tag("identity")
        first = make_file(tags=[shared])
        second = make_file(tags=[shared])

        first.delete()

        assert FileTag.objects.filter(name="identity").exists()
        assert list(second.tags.values_list("name", flat=True)) == ["identity"]

    def test_deleting_a_tag_keeps_the_file(self):
        tag = make_tag("identity")
        file = make_file(tags=[tag])

        tag.delete()

        file.refresh_from_db()
        assert file.tags.count() == 0
