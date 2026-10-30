"""Tests for the ``seed`` management command (spec 0025)."""

from io import StringIO

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from apps.cms.models import Page
from apps.core.models import Configuration
from apps.locations.models import Location
from apps.organizations.models import Organization

EXAMPLE_DIR = settings.BASE_DIR / "data" / "seed" / "example"


def write(tmp_path, name, content):
    """Write ``content`` to ``tmp_path/name`` and return its path as a string."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def run(*args, **options):
    """Run the seed command, returning its captured stdout."""
    out = StringIO()
    call_command("seed", *args, stdout=out, **options)
    return out.getvalue()


LOCATIONS = """
[seed]
model = "locations.Location"

[[rows]]
code = "IN"
name = "India"
location_type = "country"

[[rows]]
code = "IN_KL"
name = "Kerala"
location_type = "state"
parent = "IN"

[[rows]]
code = "IN_KL_ERN"
name = "Ernakulam"
location_type = "district"
parent = "IN_KL"
"""


class TestListing:
    """``--list`` reports the registered models without touching the database."""

    def test_list_models(self):
        output = run("--list")
        assert "locations.Location" in output
        assert "core.Configuration" in output
        assert "config_set, config_key" in output  # composite key is shown


@pytest.mark.django_db
class TestInsert:
    """Rows are inserted by natural key, with relationships resolved by code."""

    def test_creates_rows_and_resolves_parent(self, tmp_path):
        output = run(write(tmp_path, "locations.toml", LOCATIONS))
        assert Location.objects.count() == 3
        assert Location.objects.get(code="IN_KL").parent.code == "IN"
        assert Location.objects.get(code="IN_KL_ERN").parent.code == "IN_KL"
        assert "created 3, unchanged 0, skipped 0" in output

    def test_rerun_is_idempotent(self, tmp_path):
        path = write(tmp_path, "locations.toml", LOCATIONS)
        run(path)
        output = run(path)
        assert Location.objects.count() == 3
        assert "created 0, unchanged 3, skipped 0" in output

    def test_existing_row_is_left_untouched(self, tmp_path):
        Location.objects.create(code="IN", name="India", location_type="country")
        changed = LOCATIONS.replace('name = "India"', 'name = "Bharat"')
        output = run(write(tmp_path, "locations.toml", changed))
        # The existing IN keeps its name; the other two are created.
        assert Location.objects.get(code="IN").name == "India"
        assert Location.objects.count() == 3
        assert "created 2, unchanged 1, skipped 0" in output


@pytest.mark.django_db
class TestRelationships:
    """Foreign keys and many-to-many fields resolve by the related natural key."""

    def test_m2m_jurisdictions(self, tmp_path):
        run(write(tmp_path, "locations.toml", LOCATIONS))
        orgs = """
[seed]
model = "organizations.Organization"

[[rows]]
code = "KL_HC"
organization_type = "high_court"
name = "High Court of Kerala"
jurisdictions = ["IN_KL"]

[[rows]]
code = "ERN_DC"
organization_type = "district_court"
name = "Ernakulam District Court"
parent = "KL_HC"
jurisdictions = ["IN_KL", "IN_KL_ERN"]
"""
        run(write(tmp_path, "organizations.toml", orgs))
        hc = Organization.objects.get(code="KL_HC")
        dc = Organization.objects.get(code="ERN_DC")
        assert list(hc.jurisdictions.values_list("code", flat=True)) == ["IN_KL"]
        assert dc.parent == hc
        assert set(dc.jurisdictions.values_list("code", flat=True)) == {"IN_KL", "IN_KL_ERN"}

    def test_unresolved_fk_skips_only_that_row(self, tmp_path):
        broken = """
[seed]
model = "locations.Location"

[[rows]]
code = "IN"
name = "India"
location_type = "country"

[[rows]]
code = "ORPHAN"
name = "Orphan"
location_type = "state"
parent = "NOPE"
"""
        output = run(write(tmp_path, "locations.toml", broken))
        assert Location.objects.filter(code="IN").exists()
        assert not Location.objects.filter(code="ORPHAN").exists()
        assert "created 1, unchanged 0, skipped 1" in output

    def test_unresolved_m2m_skips_row(self, tmp_path):
        orgs = """
[seed]
model = "organizations.Organization"

[[rows]]
code = "KL_HC"
organization_type = "high_court"
name = "High Court of Kerala"
jurisdictions = ["MISSING"]
"""
        output = run(write(tmp_path, "organizations.toml", orgs))
        assert not Organization.objects.exists()
        assert "skipped 1" in output

    def test_page_categories_m2m(self, tmp_path):
        run(
            write(
                tmp_path,
                "categories.toml",
                '[seed]\nmodel = "cms.PageCategory"\n\n[[rows]]\nname = "Help"\nslug = "help"\n',
            )
        )
        run(
            write(
                tmp_path,
                "pages.toml",
                '[seed]\nmodel = "cms.Page"\n\n'
                '[[rows]]\nslug = "about"\ntitle = "About"\ncontent = "Hello"\n'
                'categories = ["help"]\n',
            )
        )
        page = Page.objects.get(slug="about")
        assert list(page.categories.values_list("slug", flat=True)) == ["help"]


@pytest.mark.django_db
class TestConfiguration:
    """Composite natural key and value coercion for Configuration."""

    def test_composite_key_and_coercion(self, tmp_path):
        toml = """
[seed]
model = "core.Configuration"

[[rows]]
config_set = "pdf"
config_key = "max_records_per_pdf"
config_value = 100
"""
        run(write(tmp_path, "config.toml", toml))
        config = Configuration.objects.get(config_set="pdf", config_key="max_records_per_pdf")
        # A native TOML integer is coerced to the stored text value.
        assert config.config_value == "100"

    def test_composite_key_rerun_is_noop(self, tmp_path):
        toml = (
            '[seed]\nmodel = "core.Configuration"\n\n'
            '[[rows]]\nconfig_set = "pdf"\nconfig_key = "k"\nconfig_value = "v"\n'
        )
        path = write(tmp_path, "config.toml", toml)
        run(path)
        output = run(path)
        assert Configuration.objects.count() == 1
        assert "unchanged 1" in output


@pytest.mark.django_db
class TestBusinessRule:
    """A business rule is validated through the model before it is stored."""

    def test_creates_rule(self, tmp_path):
        # JSON Schemas are given as TOML inline tables; the engine stores them
        # in the model's JSONField. The expression is a TOML literal string so
        # its embedded double quotes need no escaping.
        toml = """
[seed]
model = "core.BusinessRule"

[[rows]]
code = "COURT_FEE"
name = "Court fee"
engine = "rule_engine"
rule_expression = 'case_value > 100000 ? {"fee": 500, "currency": "INR"} : {"fee": 100, "currency": "INR"}'
rule_input_schema = { type = "object", properties = { case_value = { type = "number" }, case_type = { type = "string", enum = ["civil", "criminal"] } }, required = ["case_value", "case_type"], additionalProperties = false }
rule_output_schema = { type = "object", properties = { fee = { type = "number" }, currency = { type = "string" } }, required = ["fee"], additionalProperties = false }
"""
        run(write(tmp_path, "rules.toml", toml))
        from apps.core.models import BusinessRule

        rule = BusinessRule.objects.get(code="COURT_FEE")
        assert rule.engine == "rule_engine"
        assert rule.rule_input_schema["required"] == ["case_value", "case_type"]


@pytest.mark.django_db
class TestDirectoryAndFlags:
    """Directory loading, dry-run, strict and error handling."""

    def test_directory_loads_in_order(self):
        output = run(str(EXAMPLE_DIR))
        # Locations load before the organizations that cite them as jurisdictions.
        assert Location.objects.count() == 3
        assert Organization.objects.get(code="ERN_DC").parent.code == "KL_HC"
        assert Configuration.objects.filter(config_set="pdf").exists()
        assert "skipped 0" in output

    def test_dry_run_saves_nothing(self, tmp_path):
        output = run(write(tmp_path, "locations.toml", LOCATIONS), dry_run=True)
        assert Location.objects.count() == 0
        assert "Dry run: would have created 3" in output

    def test_strict_rolls_back_everything_on_skip(self, tmp_path):
        broken = """
[seed]
model = "locations.Location"

[[rows]]
code = "IN"
name = "India"
location_type = "country"

[[rows]]
code = "ORPHAN"
name = "Orphan"
location_type = "state"
parent = "NOPE"
"""
        path = write(tmp_path, "locations.toml", broken)
        with pytest.raises(CommandError, match="skipped"):
            run(path, strict=True)
        # All-or-nothing: the valid row was rolled back too.
        assert Location.objects.count() == 0

    def test_unknown_field_skips_row(self, tmp_path):
        toml = (
            '[seed]\nmodel = "locations.Location"\n\n'
            '[[rows]]\ncode = "IN"\nname = "India"\nlocation_type = "country"\nbogus = "x"\n'
        )
        output = run(write(tmp_path, "locations.toml", toml))
        assert not Location.objects.exists()
        assert "unknown field(s): bogus" in output

    def test_unknown_model_errors(self, tmp_path):
        path = write(tmp_path, "x.toml", '[seed]\nmodel = "core.Nope"\n\n[[rows]]\na = 1\n')
        with pytest.raises(CommandError, match="unknown model"):
            run(path)

    def test_missing_header_errors(self, tmp_path):
        path = write(tmp_path, "x.toml", '[[rows]]\ncode = "IN"\n')
        with pytest.raises(CommandError, match="missing a \\[seed\\] table"):
            run(path)

    def test_no_rows_errors(self, tmp_path):
        path = write(tmp_path, "x.toml", '[seed]\nmodel = "locations.Location"\n')
        with pytest.raises(CommandError, match="no \\[\\[rows\\]\\]"):
            run(path)

    def test_no_paths_errors(self):
        with pytest.raises(CommandError, match="at least one"):
            run()
