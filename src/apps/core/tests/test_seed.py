"""Tests for the ``seed`` management command (spec 0025)."""

from io import StringIO

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.cms.models import Page
from apps.core import services
from apps.core.management.commands import seed as seed_command
from apps.core.models import AdditionalAttribute, Configuration, PublicConfiguration
from apps.dristi_requests.models import ApprovalStep
from apps.hearings.models import HearingPurpose
from apps.locations.models import Location
from apps.messaging.models import MessageTemplate
from apps.organizations.models import Organization
from apps.scrutiny.models import ScrutinyRuleBinding

EXAMPLE_DIR = settings.BASE_DIR.parent / "data" / "seed" / "example"
LOCAL_DIR = settings.BASE_DIR.parent / "data" / "seed" / "local"
ATTRIBUTES_FILE = settings.BASE_DIR.parent / "data" / "seed" / "core" / "additional_attributes.toml"


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
        assert "core.PublicConfiguration" in output
        assert "config_set, config_key" in output  # composite key is shown
        for label in (
            "auth.Group",
            "messaging.MessageTemplate",
            "hearings.HearingPurpose",
            "dristi_requests.RequestType",
            "dristi_requests.ApprovalStep",
            "scrutiny.ScrutinyRuleBinding",
        ):
            assert label in output
        # Groups load before the approval steps that point at them.
        assert output.index("auth.Group") < output.index("dristi_requests.ApprovalStep")


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

    def test_rerun_matches_the_normalized_key(self, tmp_path):
        toml = (
            '[seed]\nmodel = "core.Configuration"\n\n'
            '[[rows]]\nconfig_set = "PDF"\nconfig_key = " Max "\nconfig_value = "v"\n'
        )
        path = write(tmp_path, "config.toml", toml)
        run(path)
        output = run(path, "--strict")
        assert Configuration.objects.get().config_set == "pdf"
        assert "created 0, unchanged 1, skipped 0" in output


PUBLIC_CONFIGURATIONS = """
[seed]
model = "core.PublicConfiguration"

[[rows]]
config_set = "UI_Feature_Flag"
config_key = "enable_dark_mode"
value_type = "boolean"
# A native TOML boolean; stringified to "False".
config_value = false

[[rows]]
config_set = "ui_feature_flag"
config_key = "page_size"
value_type = "integer"
config_value = 25

[[rows]]
config_set = "efiling_cheque_fraud"
config_key = "identity_drop_down"
value_type = "json"
config_value = '{"pan": "Pan Card", "epic_id": "Voter ID"}'
"""


@pytest.mark.django_db
class TestPublicConfiguration:
    """Public configuration seeds through the model's full validation (spec 0034)."""

    def test_creates_rows_and_coerces_values_to_text(self, tmp_path):
        output = run(write(tmp_path, "public.toml", PUBLIC_CONFIGURATIONS))
        assert "created 3, unchanged 0, skipped 0" in output

        flag = PublicConfiguration.objects.get(config_key="enable_dark_mode")
        assert flag.config_set == "ui_feature_flag"  # normalized
        assert flag.config_value == "False"
        assert flag.value_type == "boolean"
        assert PublicConfiguration.objects.get(config_key="page_size").config_value == "25"

    def test_rerun_is_noop(self, tmp_path):
        # "UI_Feature_Flag" is stored as "ui_feature_flag" and still matched.
        path = write(tmp_path, "public.toml", PUBLIC_CONFIGURATIONS)
        run(path)
        output = run(path, "--strict")
        assert PublicConfiguration.objects.count() == 3
        assert "created 0, unchanged 3, skipped 0" in output

    def test_typed_values_are_readable_through_services(self, tmp_path):
        run(write(tmp_path, "public.toml", PUBLIC_CONFIGURATIONS))
        assert services.get_public_bool("ui_feature_flag", "enable_dark_mode") is False
        assert services.get_public_int("ui_feature_flag", "page_size") == 25
        assert services.get_public_json("efiling_cheque_fraud", "identity_drop_down") == {
            "pan": "Pan Card",
            "epic_id": "Voter ID",
        }

    def test_secret_like_key_is_skipped_and_reported(self, tmp_path):
        toml = (
            '[seed]\nmodel = "core.PublicConfiguration"\n\n'
            '[[rows]]\nconfig_set = "gateway"\nconfig_key = "password"\nconfig_value = "x"\n\n'
            '[[rows]]\nconfig_set = "gateway"\nconfig_key = "endpoint"\nconfig_value = "https://x"\n'
        )
        output = run(write(tmp_path, "public.toml", toml))
        assert "created 1, unchanged 0, skipped 1" in output
        assert not PublicConfiguration.objects.filter(config_key="password").exists()

    def test_pair_already_in_configuration_is_skipped(self, tmp_path):
        Configuration.objects.create(config_set="pdf", config_key="max", config_value="100")
        toml = (
            '[seed]\nmodel = "core.PublicConfiguration"\n\n'
            '[[rows]]\nconfig_set = "pdf"\nconfig_key = "max"\nconfig_value = "100"\n'
        )
        output = run(write(tmp_path, "public.toml", toml))
        assert "created 0, unchanged 0, skipped 1" in output
        assert not PublicConfiguration.objects.exists()

    def test_value_not_matching_type_is_skipped(self, tmp_path):
        toml = (
            '[seed]\nmodel = "core.PublicConfiguration"\n\n'
            '[[rows]]\nconfig_set = "ui"\nconfig_key = "page_size"\n'
            'value_type = "integer"\nconfig_value = "lots"\n'
        )
        output = run(write(tmp_path, "public.toml", toml))
        assert "skipped 1" in output
        assert not PublicConfiguration.objects.exists()


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


# Codes below are prefixed TEST_ so they never collide with the rows the data
# migrations still insert into the test database (spec 0036 phase 1).
TEMPLATES = """
[seed]
model = "messaging.MessageTemplate"

[[rows]]
message_key = "TEST_OTP_SMS"
message_type = "sms"
subject = ""
content = "Use OTP {{otp}} - On Courts"
data_schema = { type = "object", properties = { otp = { type = "string" } }, required = ["otp"], additionalProperties = false }
priority = "MEDIUM"
category = "OTP"
max_retries = 1

[[rows]]
message_key = "TEST_OTP_SMS"
message_type = "email"
subject = "Your OTP"
content = "Use OTP {{otp}}"
"""

REQUESTS = (
    """
[seed]
model = "auth.Group"

[[rows]]
name = "TEST_APPROVER"
""",
    """
[seed]
model = "dristi_requests.RequestType"

[[rows]]
code = "TEST_UPDATE"
name = "Test update"
schema = { type = "object", required = ["name"], properties = { name = { type = "string", minLength = 1 } } }
min_documents = 1
is_active = true
""",
    """
[seed]
model = "dristi_requests.ApprovalStep"

[[rows]]
request_type = "TEST_UPDATE"
order = 0
approver_role = "TEST_APPROVER"
approver_group = "TEST_APPROVER"
condition = {}
""",
)

BINDINGS = """
[seed]
model = "scrutiny.ScrutinyRuleBinding"

[[rows]]
decision = "CHECKS"
rule_code = "TEST_CHECKS"
note = "National default."

[[rows]]
decision = "CHECKS"
organization = "TEST_HC"
rule_code = "TEST_CHECKS_HC"
"""


@pytest.mark.django_db
class TestReferenceData:
    """Models the data migrations seeded, now loadable by the command (spec 0036)."""

    def test_message_templates_by_composite_key(self, tmp_path):
        path = write(tmp_path, "templates.toml", TEMPLATES)
        assert "created 2, unchanged 0, skipped 0" in run(path)
        sms = MessageTemplate.objects.get(message_key="TEST_OTP_SMS", message_type="sms")
        assert sms.category == "OTP"
        assert sms.max_retries == 1
        assert sms.data_schema["required"] == ["otp"]
        assert "created 0, unchanged 2, skipped 0" in run(path, "--strict")

    def test_existing_template_is_left_untouched(self, tmp_path):
        MessageTemplate.objects.create(
            message_key="TEST_OTP_SMS", message_type="sms", content="Original {{otp}}"
        )
        run(write(tmp_path, "templates.toml", TEMPLATES))
        sms = MessageTemplate.objects.get(message_key="TEST_OTP_SMS", message_type="sms")
        assert sms.content == "Original {{otp}}"

    def test_invalid_template_is_skipped(self, tmp_path):
        toml = (
            '[seed]\nmodel = "messaging.MessageTemplate"\n\n'
            '[[rows]]\nmessage_key = "lower_key"\nmessage_type = "sms"\ncontent = "x"\n'
        )
        output = run(write(tmp_path, "templates.toml", toml))
        assert "skipped 1" in output
        assert "message_key" in output
        assert not MessageTemplate.objects.filter(message_key="lower_key").exists()

    def test_hearing_purposes(self, tmp_path):
        toml = (
            '[seed]\nmodel = "hearings.HearingPurpose"\n\n'
            '[[rows]]\ncode = "TEST_PURPOSE"\nlabel = "Test purpose"\nsequence = 99\n'
        )
        path = write(tmp_path, "purposes.toml", toml)
        assert "created 1, unchanged 0, skipped 0" in run(path)
        assert HearingPurpose.objects.get(code="TEST_PURPOSE").sequence == 99
        assert "created 0, unchanged 1, skipped 0" in run(path)

    def test_existing_purpose_is_unchanged(self, tmp_path):
        # APPEARANCE is inserted by the hearings data migration today.
        assert HearingPurpose.objects.filter(code="APPEARANCE").exists()
        toml = (
            '[seed]\nmodel = "hearings.HearingPurpose"\n\n'
            '[[rows]]\ncode = "APPEARANCE"\nlabel = "Changed"\nsequence = 5\n'
        )
        assert "created 0, unchanged 1, skipped 0" in run(write(tmp_path, "p.toml", toml))
        assert HearingPurpose.objects.get(code="APPEARANCE").label == "Appearance"

    def test_request_type_with_approval_step(self, tmp_path):
        paths = [write(tmp_path, f"{i}.toml", text) for i, text in enumerate(REQUESTS)]
        # Passed in reverse: load order still puts groups and types first.
        output = run(*reversed(paths), "--strict")
        assert "skipped 0" in output
        step = ApprovalStep.objects.get(request_type__code="TEST_UPDATE", order=0)
        assert step.approver_group == Group.objects.get(name="TEST_APPROVER")
        assert step.request_type.min_documents == 1
        # The FK in the natural key is matched by the request type's code.
        output = run(*paths, "--strict")
        assert "created 0, unchanged 1, skipped 0" in output
        assert ApprovalStep.objects.filter(request_type__code="TEST_UPDATE").count() == 1

    def test_existing_group_is_unchanged(self, tmp_path):
        Group.objects.create(name="TEST_APPROVER")
        output = run(write(tmp_path, "groups.toml", REQUESTS[0]))
        assert "created 0, unchanged 1, skipped 0" in output

    def test_unresolved_fk_in_key_skips_row(self, tmp_path):
        path = write(tmp_path, "steps.toml", REQUESTS[2].replace("TEST_APPROVER", "TEST_X"))
        output = run(path)
        assert "skipped 1" in output
        assert "request_type: no dristi_requests.RequestType with code='TEST_UPDATE'" in output
        with pytest.raises(CommandError, match="skipped"):
            run(path, strict=True)

    def test_rule_bindings_national_and_scoped(self, tmp_path):
        # Drop the national default the scrutiny data migration inserts.
        ScrutinyRuleBinding.objects.all().delete()
        Organization.objects.create(
            code="TEST_HC", name="Test High Court", organization_type="high_court"
        )
        path = write(tmp_path, "bindings.toml", BINDINGS)
        assert "created 2, unchanged 0, skipped 0" in run(path, "--strict")
        national = ScrutinyRuleBinding.objects.get(organization__isnull=True)
        assert national.rule_code == "TEST_CHECKS"
        scoped = ScrutinyRuleBinding.objects.get(organization__code="TEST_HC")
        assert scoped.rule_code == "TEST_CHECKS_HC"
        # An empty organization is matched as NULL, so the rerun is a no-op.
        assert "created 0, unchanged 2, skipped 0" in run(path, "--strict")

    def test_empty_non_fk_key_is_still_rejected(self, tmp_path):
        toml = (
            '[seed]\nmodel = "scrutiny.ScrutinyRuleBinding"\n\n'
            '[[rows]]\nrule_code = "TEST_CHECKS"\n'
        )
        output = run(write(tmp_path, "bindings.toml", toml))
        assert "missing key field(s): decision" in output


@pytest.mark.django_db
class TestDirectoryAndFlags:
    """Directory loading, dry-run, strict and error handling."""

    def test_directory_loads_in_order(self):
        output = run(str(EXAMPLE_DIR))
        # Locations load before the organizations that cite them as jurisdictions.
        assert Location.objects.count() == 3
        assert Organization.objects.get(code="ERN_DC").parent.code == "KL_HC"
        assert Configuration.objects.filter(config_set="pdf").exists()
        assert services.get_public_json("efiling_cheque_fraud", "identity_drop_down") == {
            "pan": "Pan Card",
            "epic_id": "Voter ID",
        }
        assert "skipped 0" in output

    def test_same_model_files_load_in_given_order(self, tmp_path):
        # The parent file is passed first even though its name sorts last, so a
        # filename sort would load the child first and fail to resolve it. The
        # command keeps the given order, so the state's parent resolves.
        parent = write(
            tmp_path,
            "z_country.toml",
            '[seed]\nmodel = "locations.Location"\n\n'
            '[[rows]]\ncode = "IN"\nname = "India"\nlocation_type = "country"\n',
        )
        child = write(
            tmp_path,
            "a_state.toml",
            '[seed]\nmodel = "locations.Location"\n\n'
            '[[rows]]\ncode = "IN_KL"\nname = "Kerala"\nlocation_type = "state"\nparent = "IN"\n',
        )
        output = run(parent, child)
        assert Location.objects.get(code="IN_KL").parent.code == "IN"
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


MEMBERSHIP = """
[seed]
model = "users.User_groups"

[[rows]]
user = "+919000000001"
group = "BAR_ID_APPROVER"
"""


@pytest.mark.django_db
class TestGroupMembership:
    """User-group membership is seeded by mobile number and group name."""

    @pytest.fixture
    def approvers(self):
        group, _ = Group.objects.get_or_create(name="BAR_ID_APPROVER")
        return group

    @pytest.fixture
    def user(self):
        return get_user_model().objects.create_user("+919000000001", password="pw")

    def test_adds_user_to_group(self, tmp_path, approvers, user):
        output = run(write(tmp_path, "members.toml", MEMBERSHIP))
        assert approvers.user_set.filter(pk=user.pk).exists()
        assert "created 1, unchanged 0, skipped 0" in output

    def test_rerun_is_idempotent(self, tmp_path, approvers, user):
        path = write(tmp_path, "members.toml", MEMBERSHIP)
        run(path)
        output = run(path)
        assert approvers.user_set.filter(pk=user.pk).count() == 1
        assert "created 0, unchanged 1, skipped 0" in output

    def test_existing_member_is_unchanged(self, tmp_path, approvers, user):
        user.groups.add(approvers)
        output = run(write(tmp_path, "members.toml", MEMBERSHIP))
        assert approvers.user_set.count() == 1
        assert "created 0, unchanged 1, skipped 0" in output

    def test_unknown_user_skips_row(self, tmp_path, approvers):
        output = run(write(tmp_path, "members.toml", MEMBERSHIP))
        assert not approvers.user_set.exists()
        assert "no users.User with mobile_number='+919000000001'" in output

    def test_unknown_group_skips_row(self, tmp_path, user):
        toml = MEMBERSHIP.replace("BAR_ID_APPROVER", "NO_SUCH_GROUP")
        output = run(write(tmp_path, "members.toml", toml))
        assert not user.groups.exists()
        assert "no auth.Group with name='NO_SUCH_GROUP'" in output

    def test_dry_run_adds_nobody(self, tmp_path, approvers, user):
        output = run(write(tmp_path, "members.toml", MEMBERSHIP), dry_run=True)
        assert not approvers.user_set.exists()
        assert "Dry run: would have created 1" in output

    def test_listed_with_composite_key(self):
        assert "users.User_groups  (key: user, group)" in run("--list")

    def test_local_seed_file_adds_the_documented_superuser(self, approvers):
        superuser = get_user_model().objects.create_superuser("+919999999999", password="pw")
        output = run(str(LOCAL_DIR))
        assert approvers.user_set.filter(pk=superuser.pk).exists()
        assert "skipped 0" in output


def bank_rows(count, parent="IN_KL_ERN", start=1):
    """Return ``count`` bank rows as TOML, IFSCs numbered from ``start``."""
    return "".join(
        f"""
[[rows]]
code = "TEST{number:07d}"
name = "Test Bank - Branch {number}"
short_name = "TEST{number:07d}"
location_type = "bank"
parent = "{parent}"
additional_attributes = {{ address = "{number} MG Road, Kochi 682001" }}
"""
        for number in range(start, start + count)
    )


def banks_file(tmp_path, rows, name="banks.toml"):
    """Write a locations file holding ``rows`` and return its path."""
    return write(tmp_path, name, '[seed]\nmodel = "locations.Location"\n' + rows)


@pytest.mark.django_db
class TestBulkLocations:
    """Locations load in batches (pincodes and banks run to lakhs of rows)."""

    @pytest.fixture(autouse=True)
    def hierarchy(self, tmp_path):
        """Seed the core attribute definitions and IN -> IN_KL -> IN_KL_ERN."""
        run(str(ATTRIBUTES_FILE), write(tmp_path, "locations.toml", LOCATIONS))

    def test_creates_banks_in_the_issue_shape(self, tmp_path):
        output = run(banks_file(tmp_path, bank_rows(3)))

        bank = Location.objects.get(code="TEST0000002")
        assert bank.parent.code == "IN_KL_ERN"
        assert (bank.name, bank.short_name) == ("Test Bank - Branch 2", "TEST0000002")
        # Every defined attribute is nullable, so the ones a bank lacks are null.
        assert bank.additional_attributes == {
            "address": "2 MG Road, Kochi 682001",
            "police_district": None,
        }
        assert "created 3, unchanged 0, skipped 0" in output

    def test_rerun_is_idempotent(self, tmp_path):
        path = banks_file(tmp_path, bank_rows(3))
        run(path)

        output = run(path)

        assert Location.objects.filter(location_type="bank").count() == 3
        assert "created 0, unchanged 3, skipped 0" in output

    def test_invalid_row_is_skipped_and_reported(self, tmp_path):
        # Not an IFSC: the fifth character must be 0.
        rows = bank_rows(2) + bank_rows(1, start=3).replace(
            'code = "TEST0000003"', 'code = "TEST1000003"'
        )

        output = run(banks_file(tmp_path, rows))

        assert not Location.objects.filter(code="TEST1000003").exists()
        assert "row 3: skipped — code: A bank's code must be its IFSC" in output
        assert "created 2, unchanged 0, skipped 1" in output

    def test_bank_under_an_unknown_parent_is_skipped(self, tmp_path):
        output = run(banks_file(tmp_path, bank_rows(1, parent="IN_XX")))

        assert "parent: no locations.Location with code='IN_XX'" in output
        assert "created 0, unchanged 0, skipped 1" in output

    def test_list_as_a_parent_is_skipped_not_a_crash(self, tmp_path):
        rows = bank_rows(1).replace('parent = "IN_KL_ERN"', 'parent = ["IN_KL_ERN"]')

        output = run(banks_file(tmp_path, rows))

        assert "skipped 1" in output

    def test_duplicate_key_in_one_file_counts_as_unchanged(self, tmp_path):
        output = run(banks_file(tmp_path, bank_rows(2) + bank_rows(1)))

        assert Location.objects.filter(location_type="bank").count() == 2
        assert "created 2, unchanged 1, skipped 0" in output

    # A TOML integer key is stored as text; it must match that text on a re-run,
    # against a string of the same code in the file, and as a parent reference.
    STATION = """
[[rows]]
code = 15281001
name = "Alappuzha North"
location_type = "police_station"
parent = "IN_KL_ERN"
"""
    NUMERIC_DISTRICT = """
[[rows]]
code = "682001"
name = "Numeric District"
location_type = "district"
parent = "IN_KL"
"""
    UNDER_NUMERIC = """
[[rows]]
code = "IN_KL_CHILD"
name = "Child"
location_type = "district"
parent = 682001
"""

    def test_integer_code_rerun_is_unchanged(self, tmp_path):
        path = banks_file(tmp_path, self.STATION)
        assert "created 1, unchanged 0, skipped 0" in run(path)

        output = run(path)

        assert Location.objects.filter(code="15281001").count() == 1
        assert "created 0, unchanged 1, skipped 0" in output

    def test_integer_and_string_of_one_code_in_a_file(self, tmp_path):
        quoted = self.STATION.replace("code = 15281001", 'code = "15281001"')

        output = run(banks_file(tmp_path, quoted + self.STATION))

        assert Location.objects.filter(code="15281001").count() == 1
        assert "created 1, unchanged 1, skipped 0" in output

    def test_integer_parent_created_earlier_in_the_file(self, tmp_path):
        output = run(banks_file(tmp_path, self.NUMERIC_DISTRICT + self.UNDER_NUMERIC))

        assert Location.objects.get(code="IN_KL_CHILD").parent.code == "682001"
        assert "created 2, unchanged 0, skipped 0" in output

    def test_parent_created_in_an_earlier_batch_resolves(self, tmp_path, monkeypatch):
        monkeypatch.setattr(seed_command, "BULK_BATCH_SIZE", 2)
        district = """
[[rows]]
code = "IN_KL_TVM"
name = "Thiruvananthapuram"
location_type = "district"
parent = "IN_KL"
"""
        # The district lands in the first batch, its banks in later ones.
        rows = bank_rows(1) + district + bank_rows(4, parent="IN_KL_TVM", start=2)

        output = run(banks_file(tmp_path, rows))

        assert set(
            Location.objects.filter(parent__code="IN_KL_TVM").values_list("code", flat=True)
        ) == {"TEST0000002", "TEST0000003", "TEST0000004", "TEST0000005"}
        assert "created 6, unchanged 0, skipped 0" in output

    def test_dry_run_saves_nothing(self, tmp_path):
        output = run(banks_file(tmp_path, bank_rows(3)), dry_run=True)

        assert not Location.objects.filter(location_type="bank").exists()
        assert "Dry run: would have created 3" in output

    def test_query_count_does_not_grow_with_rows(self, tmp_path):
        def queries(rows, name):
            path = banks_file(tmp_path, rows, name)
            with CaptureQueriesContext(connection) as captured:
                run(path)
            return len(captured.captured_queries)

        few = queries(bank_rows(5), "few.toml")
        # Under 84 rows: SQLite's bulk_create splits larger inserts by its
        # parameter limit, which would add queries unrelated to the engine.
        many = queries(bank_rows(80, start=6), "many.toml")

        assert Location.objects.filter(location_type="bank").count() == 85
        assert many == few


@pytest.mark.django_db
class TestAdditionalAttribute:
    """Attribute definitions seed by (content type, name), the type given as app.model."""

    @pytest.mark.parametrize("name", ["address", "police_district"])
    def test_core_file_defines_the_location_attributes(self, name):
        output = run(str(ATTRIBUTES_FILE))

        attribute = AdditionalAttribute.objects.get(name=name)
        assert attribute.content_type.model_class() is Location
        assert (attribute.data_type, attribute.is_nullable) == ("character", True)
        assert "created 2, unchanged 0, skipped 0" in output

    def test_rerun_matches_on_content_type_and_name(self):
        run(str(ATTRIBUTES_FILE))

        output = run(str(ATTRIBUTES_FILE))

        assert AdditionalAttribute.objects.filter(name="address").count() == 1
        assert "created 0, unchanged 2, skipped 0" in output

    def test_same_name_on_another_model_is_a_new_row(self, tmp_path):
        run(str(ATTRIBUTES_FILE))
        other = """
[seed]
model = "core.AdditionalAttribute"

[[rows]]
content_type = "organizations.organization"
name = "address"
data_type = "character"
"""

        output = run(write(tmp_path, "attributes.toml", other))

        assert AdditionalAttribute.objects.filter(name="address").count() == 2
        assert "created 1, unchanged 0, skipped 0" in output

    @pytest.mark.parametrize("content_type", ["locations.nope", "locations", "a.b.c"])
    def test_unknown_content_type_is_skipped(self, tmp_path, content_type):
        toml = f"""
[seed]
model = "core.AdditionalAttribute"

[[rows]]
content_type = "{content_type}"
name = "address"
data_type = "character"
"""

        output = run(write(tmp_path, "attributes.toml", toml))

        assert not AdditionalAttribute.objects.exists()
        assert f"content_type: no contenttypes.ContentType with natural key '{content_type}'" in (
            output
        )

    def test_definitions_load_before_the_locations_that_use_them(self, tmp_path):
        # Passed after the banks, but the attribute spec's load order puts it first.
        banks = banks_file(tmp_path, bank_rows(1))
        locations = write(tmp_path, "locations.toml", LOCATIONS)

        output = run(locations, banks, str(ATTRIBUTES_FILE))

        assert Location.objects.get(code="TEST0000001").additional_attributes == {
            "address": "1 MG Road, Kochi 682001",
            "police_district": None,
        }
        assert "skipped 0" in output


POLICE_STATIONS_FILE = (
    settings.BASE_DIR.parent / "data" / "seed" / "kerala" / "police_stations.toml"
)
# The Kerala districts as the India Post-derived districts.toml names them.
KERALA_DISTRICTS = (
    "ALAPPUZHA",
    "ERNAKULAM",
    "IDUKKI",
    "KANNUR",
    "KASARAGOD",
    "KOLLAM",
    "KOTTAYAM",
    "KOZHIKODE",
    "MALAPPURAM",
    "PALAKKAD",
    "PATHANAMTHITTA",
    "THIRUVANANTHAPURAM",
    "THRISSUR",
    "WAYANAD",
)


@pytest.mark.django_db
class TestKeralaPoliceStations:
    """The shipped police station file loads whole onto the Kerala districts (issue #250)."""

    @pytest.fixture(autouse=True)
    def kerala(self, tmp_path):
        """Seed the core attribute definitions, IN_KERALA and its 14 districts."""
        rows = "".join(
            f'\n[[rows]]\ncode = "IN_KERALA_{name}"\nname = "{name.title()}"\n'
            f'location_type = "district"\nparent = "IN_KERALA"\n'
            for name in KERALA_DISTRICTS
        )
        kerala = (
            '[seed]\nmodel = "locations.Location"\n\n[[rows]]\ncode = "IN"\nname = "India"\n'
            'location_type = "country"\n\n[[rows]]\ncode = "IN_KERALA"\nname = "Kerala"\n'
            'location_type = "state"\nparent = "IN"\n' + rows
        )
        run(str(ATTRIBUTES_FILE), write(tmp_path, "kerala.toml", kerala))

    def test_every_station_loads(self):
        output = run(str(POLICE_STATIONS_FILE))

        assert "created 517, unchanged 0, skipped 0" in output
        assert Location.objects.filter(location_type="police_station").count() == 517

    def test_each_district_and_the_state_hold_stations(self):
        run(str(POLICE_STATIONS_FILE))

        stations = Location.objects.filter(location_type="police_station")
        parents = set(stations.values_list("parent__code", flat=True))
        assert parents == {"IN_KERALA"} | {f"IN_KERALA_{name}" for name in KERALA_DISTRICTS}
        # Only the state-wide railway police and CID stations sit under the state.
        assert {
            station.additional_attributes["police_district"]
            for station in stations.filter(parent__code="IN_KERALA")
        } == {"RAILWAY POLICE", "C I D"}
        assert stations.filter(parent__code="IN_KERALA").count() == 15

    def test_a_split_police_district_keeps_its_name(self):
        run(str(POLICE_STATIONS_FILE))

        east = Location.objects.get(code="15996001")
        assert (east.name, east.parent.code) == ("THRISSUR EAST", "IN_KERALA_THRISSUR")
        assert east.additional_attributes == {"address": None, "police_district": "THRISSUR CITY"}

    def test_rerun_is_idempotent(self):
        run(str(POLICE_STATIONS_FILE))

        output = run(str(POLICE_STATIONS_FILE))

        assert "created 0, unchanged 517, skipped 0" in output
