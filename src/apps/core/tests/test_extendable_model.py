"""Tests for additional attributes, validators, BaseExtendableModel, and AdditionalAttribute."""

from datetime import UTC

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.core.models import AdditionalAttribute, ApiVersionChangeLog
from apps.core.validators import (
    coerce_boolean,
    coerce_character,
    coerce_date,
    coerce_datetime,
    coerce_float,
    coerce_integer,
    coerce_json,
    coerce_number,
    coerce_value,
    validate_attribute_name,
)


class TestValidators:
    """Tests for coercion and validation helpers."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            (False, False),
            (0, False),
            (1, True),
            ("true", True),
            ("True", True),
            ("FALSE", False),
            ("false", False),
        ],
    )
    def test_coerce_boolean_valid(self, value, expected):
        assert coerce_boolean(value) is expected

    @pytest.mark.parametrize("value", ["yes", "no", "y", "n", "1", "0", "maybe", 2, []])
    def test_coerce_boolean_invalid(self, value):
        with pytest.raises(ValidationError):
            coerce_boolean(value)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (5, 5),
            ("5", 5),
            (5.0, 5),
            ("5.0", 5),
        ],
    )
    def test_coerce_integer_valid(self, value, expected):
        assert coerce_integer(value) == expected

    @pytest.mark.parametrize("value", [True, 5.5, "5.5", "abc", None])
    def test_coerce_integer_invalid(self, value):
        with pytest.raises(ValidationError):
            coerce_integer(value)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (5, 5.0),
            (5.5, 5.5),
            ("5.5", 5.5),
            ("5", 5.0),
        ],
    )
    def test_coerce_float_valid(self, value, expected):
        assert coerce_float(value) == expected

    @pytest.mark.parametrize("value", [True, "abc", None])
    def test_coerce_float_invalid(self, value):
        with pytest.raises(ValidationError):
            coerce_float(value)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (5, 5),
            (5.5, 5.5),
            ("5", 5),
            ("5.5", 5.5),
        ],
    )
    def test_coerce_number_valid(self, value, expected):
        assert coerce_number(value) == expected
        assert type(coerce_number(value)) is type(expected)

    @pytest.mark.parametrize("value", [True, "abc", None])
    def test_coerce_number_invalid(self, value):
        with pytest.raises(ValidationError):
            coerce_number(value)

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("hello", "hello"),
            (123, "123"),
            (1.5, "1.5"),
            (True, "True"),
        ],
    )
    def test_coerce_character_valid(self, value, expected):
        assert coerce_character(value) == expected

    def test_coerce_character_none_invalid(self):
        with pytest.raises(ValidationError):
            coerce_character(None)

    def test_coerce_datetime_from_object(self):
        from datetime import datetime

        dt = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)
        assert coerce_datetime(dt) == "2026-09-08T12:30:00+00:00"

    def test_coerce_datetime_from_string(self):
        assert coerce_datetime("2026-09-08T12:30:00+00:00") == "2026-09-08T12:30:00+00:00"

    @pytest.mark.parametrize("value", ["not-a-date", "2026-09-08", None])
    def test_coerce_datetime_invalid(self, value):
        with pytest.raises(ValidationError):
            coerce_datetime(value)

    def test_coerce_date_from_object(self):
        from datetime import date

        assert coerce_date(date(2026, 9, 8)) == "2026-09-08"

    def test_coerce_date_from_string(self):
        assert coerce_date("2026-09-08") == "2026-09-08"

    @pytest.mark.parametrize("value", ["not-a-date", "2026-09-08T12:00:00", None])
    def test_coerce_date_invalid(self, value):
        with pytest.raises(ValidationError):
            coerce_date(value)

    def test_coerce_json_serializable(self):
        assert coerce_json({"a": [1, 2, 3]}) == {"a": [1, 2, 3]}

    def test_coerce_json_not_serializable(self):
        with pytest.raises(ValidationError):
            coerce_json(set())

    @pytest.mark.parametrize("data_type", ["integer", "float", "number"])
    def test_bools_rejected_for_numeric_types(self, data_type):
        with pytest.raises(ValidationError):
            coerce_value(True, data_type)

    @pytest.mark.parametrize(
        "name",
        ["valid", "valid_name", "valid123", "a_b_c"],
    )
    def test_validate_attribute_name_valid(self, name):
        validate_attribute_name(name)  # should not raise

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "_invalid",
            "Invalid",
            "invalid-name",
            "123_invalid",
            "invalid.name",
            "invalid name",
        ],
    )
    def test_validate_attribute_name_invalid(self, name):
        with pytest.raises(ValidationError):
            validate_attribute_name(name)


@pytest.mark.django_db
class TestAdditionalAttributeModel:
    """Tests for the AdditionalAttribute metadata model."""

    @pytest.fixture
    def content_type(self):
        return ContentType.objects.get_for_model(ApiVersionChangeLog)

    def test_create_valid(self, content_type):
        attr = AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
            default_value=None,
        )
        assert attr.pk is not None
        assert attr.name == "age"

    def test_unique_together(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
        )
        with pytest.raises(ValidationError):
            attr = AdditionalAttribute(
                content_type=content_type,
                name="age",
                data_type="float",
                is_nullable=True,
            )
            attr.full_clean()

    def test_invalid_name_raises(self, content_type):
        attr = AdditionalAttribute(
            content_type=content_type,
            name="Invalid Name",
            data_type="integer",
            is_nullable=True,
        )
        with pytest.raises(ValidationError):
            attr.full_clean()

    def test_default_value_type_mismatch(self, content_type):
        attr = AdditionalAttribute(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
            default_value="twenty",
        )
        with pytest.raises(ValidationError):
            attr.full_clean()

    def test_non_nullable_requires_default(self, content_type):
        attr = AdditionalAttribute(
            content_type=content_type,
            name="department",
            data_type="character",
            is_nullable=False,
            default_value=None,
        )
        with pytest.raises(ValidationError):
            attr.full_clean()

    def test_non_nullable_with_default_is_valid(self, content_type):
        attr = AdditionalAttribute(
            content_type=content_type,
            name="department",
            data_type="character",
            is_nullable=False,
            default_value="Engineering",
        )
        attr.full_clean()  # should not raise
        attr.save()
        assert attr.pk is not None


@pytest.mark.django_db
class TestBaseExtendableModel:
    """Tests for BaseExtendableModel validation and default handling."""

    @pytest.fixture
    def content_type(self):
        return ContentType.objects.get_for_model(ApiVersionChangeLog)

    def test_save_with_no_definitions_allows_empty_dict(self):
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Test changelog.", additional_attributes={}
        )
        assert demo.additional_attributes == {}

    def test_unknown_attribute_rejected(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="allowed",
            data_type="integer",
            is_nullable=True,
        )
        demo = ApiVersionChangeLog(
            version="1.0.0",
            change_log="Test changelog.",
            additional_attributes={"allowed": 1, "unknown": 2},
        )
        with pytest.raises(ValidationError):
            demo.save()

    def test_missing_non_nullable_without_default_rejected(self, content_type):
        # AdditionalAttribute.save() forbids creating non-nullable attributes
        # without a default, so bypass save() to test BaseExtendableModel's
        # defensive validation.
        attr = AdditionalAttribute(
            content_type=content_type,
            name="required_no_default",
            data_type="character",
            is_nullable=False,
            default_value=None,
        )
        AdditionalAttribute.objects.bulk_create([attr])
        demo = ApiVersionChangeLog(
            version="1.0.0", change_log="Test changelog.", additional_attributes={}
        )
        with pytest.raises(ValidationError):
            demo.save()

    def test_default_applied_for_missing_attribute(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="department",
            data_type="character",
            is_nullable=False,
            default_value="Engineering",
        )
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Test changelog.", additional_attributes={}
        )
        assert demo.additional_attributes == {"department": "Engineering"}

    def test_nullable_missing_defaults_to_none(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="optional",
            data_type="integer",
            is_nullable=True,
            default_value=None,
        )
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Test changelog.", additional_attributes={}
        )
        assert demo.additional_attributes == {"optional": None}

    def test_null_value_for_non_nullable_rejected(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="required",
            data_type="integer",
            is_nullable=False,
            default_value=0,
        )
        demo = ApiVersionChangeLog(
            version="1.0.0", change_log="Test changelog.", additional_attributes={"required": None}
        )
        with pytest.raises(ValidationError):
            demo.save()

    def test_type_coercion_on_save(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
        )
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Test changelog.", additional_attributes={"age": "25"}
        )
        assert demo.additional_attributes == {"age": 25}

    def test_datetime_stored_as_iso_string(self, content_type):
        from datetime import datetime

        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="started_at",
            data_type="datetime",
            is_nullable=True,
        )
        dt = datetime(2026, 9, 8, 12, 30, tzinfo=UTC)
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Test changelog.", additional_attributes={"started_at": dt}
        )
        assert demo.additional_attributes == {"started_at": "2026-09-08T12:30:00+00:00"}

    def test_date_stored_as_iso_string(self, content_type):
        from datetime import date

        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="birthday",
            data_type="date",
            is_nullable=True,
        )
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Test changelog.",
            additional_attributes={"birthday": date(2026, 9, 8)},
        )
        assert demo.additional_attributes == {"birthday": "2026-09-08"}

    def test_json_attribute_serializability(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="metadata",
            data_type="json",
            is_nullable=True,
        )
        payload = {"nested": [1, 2, {"a": "b"}]}
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Test changelog.",
            additional_attributes={"metadata": payload},
        )
        assert demo.additional_attributes == {"metadata": payload}

    def test_multiple_attributes_handled(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="age",
            data_type="integer",
            is_nullable=True,
        )
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="active",
            data_type="boolean",
            is_nullable=False,
            default_value=False,
        )
        demo = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Test changelog.", additional_attributes={"age": "30"}
        )
        assert demo.additional_attributes == {"age": 30, "active": False}

    def test_full_clean_can_be_called_directly(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="score",
            data_type="float",
            is_nullable=True,
        )
        demo = ApiVersionChangeLog(
            version="1.0.0", change_log="Test changelog.", additional_attributes={"score": "3.14"}
        )
        demo.full_clean()
        assert demo.additional_attributes == {"score": 3.14}

    def test_api_changelog_example_attributes(self, content_type):
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="breaking_change",
            data_type="boolean",
            is_nullable=False,
            default_value=False,
        )
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="release_type",
            data_type="character",
            is_nullable=False,
            default_value="minor",
        )
        AdditionalAttribute.objects.create(
            content_type=content_type,
            name="deprecated",
            data_type="boolean",
            is_nullable=True,
            default_value=None,
        )
        demo = ApiVersionChangeLog.objects.create(
            version="v2.1",
            change_log="Added additional attributes support.",
            additional_attributes={"deprecated": False},
        )
        assert demo.additional_attributes == {
            "breaking_change": False,
            "release_type": "minor",
            "deprecated": False,
        }
