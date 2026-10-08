"""DirectMapper, DerivedMapper, FormattingMapper and the DataMapper facade (#5)."""

import pytest

from apps.pdf.exceptions import PDFConfigurationError, PDFRequestDataError
from apps.pdf.services.context import RequestContext
from apps.pdf.services.mapping import DataMapper
from apps.pdf.services.mapping.derived import DerivedMapper
from apps.pdf.services.mapping.direct import DirectMapper
from apps.pdf.services.mapping.formatting import FormattingMapper, format_date, format_number

DATA = {
    "case": {"number": "cc/1/2026", "type": "DC"},
    "accused": [{"name": "Ravi", "age": 30}, {"name": "Mini", "age": 17}],
    "tags": ["a", "b"],
}


class TestDirectMapper:
    mapper = DirectMapper()

    def test_scalar_path(self):
        assert self.mapper.map({"target": "n", "path": "$.case.number"}, DATA) == "cc/1/2026"

    def test_case_transform(self):
        spec = {"target": "n", "path": "$.case.number", "transform": "upper"}
        assert self.mapper.map(spec, DATA) == "CC/1/2026"

    def test_many_returns_every_match(self):
        spec = {"target": "names", "path": "$.accused[*].name", "many": True}
        assert self.mapper.map(spec, DATA) == ["Ravi", "Mini"]

    def test_columns_project_objects(self):
        spec = {
            "target": "rows",
            "path": "$.accused[*]",
            "columns": {"who": "$.name", "x": "$.missing"},
        }
        assert self.mapper.map(spec, DATA) == [
            {"who": "Ravi", "x": None},
            {"who": "Mini", "x": None},
        ]

    def test_labels_translate_codes(self):
        spec = {"target": "t", "path": "$.case.type", "labels": {"DC": "District Court"}}
        assert self.mapper.map(spec, DATA) == "District Court"

    def test_labels_on_lists_keep_unknown_codes(self):
        spec = {"target": "t", "path": "$.tags[*]", "many": True, "labels": {"a": "Alpha"}}
        assert self.mapper.map(spec, DATA) == ["Alpha", "b"]

    def test_constant_value(self):
        assert self.mapper.map({"target": "t", "value": "SUMMONS"}, DATA) == "SUMMONS"

    def test_missing_required_value_raises(self):
        with pytest.raises(PDFRequestDataError):
            self.mapper.map({"target": "x", "path": "$.nope"}, DATA)

    def test_missing_value_uses_default(self):
        assert self.mapper.map({"target": "x", "path": "$.nope", "default": "-"}, DATA) == "-"

    def test_missing_optional_value_is_none(self):
        assert self.mapper.map({"target": "x", "path": "$.nope", "required": False}, DATA) is None

    def test_jsonpath_filter_expressions_are_supported(self):
        spec = {"target": "minors", "path": "$.accused[?(@.age < 18)].name", "many": True}
        assert self.mapper.map(spec, DATA) == ["Mini"]

    def test_invalid_jsonpath_is_a_configuration_error(self):
        with pytest.raises(PDFConfigurationError):
            self.mapper.map({"target": "x", "path": "$[[["}, DATA)


class TestDerivedMapper:
    mapper = DerivedMapper()

    def test_expression(self):
        variables = {"data": DATA, "names": ["a", "b"]}
        assert self.mapper.map({"expression": "names | length"}, variables) == 2

    def test_registered_function(self):
        assert self.mapper.map({"function": "sum", "args": ["[1, 2, '3.5']"]}, {}) == 6.5

    def test_join_and_coalesce(self):
        variables = {"xs": ["a", None, "b"]}
        assert self.mapper.map({"function": "join", "args": ["xs", "' / '"]}, variables) == "a / b"
        assert self.mapper.map({"function": "coalesce", "args": ["none", "''", "'x'"]}, {}) == "x"

    def test_unknown_function_is_a_configuration_error(self):
        with pytest.raises(PDFConfigurationError):
            self.mapper.map({"function": "eval"}, {})

    def test_sandbox_blocks_attribute_escapes(self):
        with pytest.raises(PDFConfigurationError):
            self.mapper.map({"expression": "data.__class__.__mro__"}, {"data": {}})

    def test_missing_variable_is_a_request_error(self):
        with pytest.raises(PDFRequestDataError):
            self.mapper.map({"expression": "nope + 1"}, {})


class TestFormatting:
    def test_date_from_iso_converts_to_ist(self):
        assert format_date("2026-10-01T20:00:00Z", "%d %b %Y %H:%M") == "02 Oct 2026 01:30"

    def test_date_from_epoch_ms(self):
        assert format_date(0, "%Y", input_format="epoch_ms") == "1970"

    def test_invalid_date_is_a_request_error(self):
        with pytest.raises(PDFRequestDataError):
            format_date("not a date")

    @pytest.mark.parametrize(
        ("value", "kwargs", "expected"),
        [
            (1234567.891, {"decimals": 2}, "1,234,567.89"),
            (1234567, {"grouping": "indian"}, "12,34,567"),
            ("2.5", {}, "3"),
            (-1234.5, {"decimals": 1, "grouping": "none"}, "-1234.5"),
            (None, {}, ""),
        ],
    )
    def test_number(self, value, kwargs, expected):
        assert format_number(value, **kwargs) == expected

    def test_formatting_mapper(self):
        spec = {"source": "data.case.number", "format": "upper"}
        assert FormattingMapper().map(spec, {"data": DATA}) == "CC/1/2026"


class TestDataMapper:
    def test_mappings_build_on_each_other_and_see_meta(self):
        config = {
            "mappings": [
                {"type": "direct", "target": "names", "path": "$.accused[*].name", "many": True},
                {"type": "derived", "target": "count", "expression": "names | length"},
                {"type": "derived", "target": "tenant", "expression": "meta.tenant_id"},
                {"type": "format", "target": "upper", "source": "names[0]", "format": "upper"},
            ]
        }
        context = RequestContext(tenant_id="kl", key="k")
        result = DataMapper(context, config).map(config, DATA)

        assert result["count"] == 2
        assert result["tenant"] == "kl"
        assert result["upper"] == "RAVI"
        assert result["data"] is DATA

    def test_unknown_mapping_type_is_rejected(self):
        config = {"mappings": [{"type": "magic", "target": "x"}]}
        with pytest.raises(PDFConfigurationError):
            DataMapper(None, config).map(config, {})
