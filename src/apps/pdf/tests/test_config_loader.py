"""PDFConfigLoader and configuration validation (#9)."""

import pytest
from django.core.exceptions import ValidationError

from apps.pdf.exceptions import PDFTemplateNotFound
from apps.pdf.models import PDFTemplate
from apps.pdf.services.config_loader import PDFConfigLoader
from apps.pdf.services.validation import validate_data_config, validate_format_config
from apps.pdf.tests.factories import DATA_CONFIG, FORMAT_CONFIG, make_template

pytestmark = pytest.mark.django_db


def test_load_returns_active_version_configuration():
    version = make_template()
    format_config, data_config, config = PDFConfigLoader.load("case-summons")

    assert format_config == FORMAT_CONFIG
    assert data_config == DATA_CONFIG
    assert config.template_version_id == str(version.id)
    assert config.version == 1


def test_load_is_cached(django_assert_num_queries):
    make_template()
    PDFConfigLoader.load("case-summons")
    with django_assert_num_queries(0):
        PDFConfigLoader.load("case-summons")


def test_new_version_takes_effect_immediately():
    make_template()
    PDFConfigLoader.load("case-summons")
    make_template(format_config={"body": [{"type": "paragraph", "text": "v2"}]})

    format_config, _, config = PDFConfigLoader.load("case-summons")
    assert config.version == 2
    assert format_config["body"][0]["text"] == "v2"


def test_deactivated_template_is_not_found():
    version = make_template()
    PDFConfigLoader.load("case-summons")
    template = version.template
    template.is_active = False
    template.save()

    with pytest.raises(PDFTemplateNotFound):
        PDFConfigLoader.load("case-summons")


def test_unknown_key_is_not_found():
    PDFTemplate.objects.create(key="empty", name="No versions")
    with pytest.raises(PDFTemplateNotFound):
        PDFConfigLoader.load("empty")
    with pytest.raises(PDFTemplateNotFound):
        PDFConfigLoader.load("missing")


def test_load_version_returns_a_specific_version():
    first = make_template()
    make_template()
    assert PDFConfigLoader.load_version(first.id).version == 1


class TestFormatConfigValidation:
    def test_valid_config(self):
        validate_format_config(FORMAT_CONFIG)

    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"body": [{"type": "paragraph"}]},
            {"body": [{"type": "paragraph", "text": "x", "extra": 1}]},
            {"body": [{"type": "paragraph", "text": "{{ unclosed"}]},
            {"body": [{"type": "table", "columns": []}]},
            {"body": [], "page": {"size": "B9"}},
            {"body": [], "styles": {"x": {"font": "comic-sans"}}},
            {"body": [{"type": "group", "blocks": [{"type": "nope"}]}]},
            {"body": [{"type": "paragraph", "text": "x", "when": "a +"}]},
        ],
    )
    def test_invalid_configs(self, config):
        with pytest.raises(ValidationError):
            validate_format_config(config)


class TestDataConfigValidation:
    def test_valid_config(self):
        validate_data_config(DATA_CONFIG)

    @pytest.mark.parametrize(
        "config",
        [
            {"mappings": [{"type": "direct", "target": "x"}]},
            {"mappings": [{"type": "direct", "target": "data", "path": "$.x"}]},
            {"mappings": [{"type": "direct", "target": "x", "path": "$.x"}] * 2},
            {"mappings": [{"type": "derived", "target": "x", "function": "eval"}]},
            {"mappings": [{"type": "external_api", "target": "x", "url": "{{ x"}]},
            {"mappings": [{"type": "format", "target": "x", "source": "a", "format": "roman"}]},
            {"significant_fields": ["$[["]},
            {"request_schema": {"type": "not-a-type"}},
            {"unknown": True},
        ],
    )
    def test_invalid_configs(self, config):
        with pytest.raises(ValidationError):
            validate_data_config(config)
