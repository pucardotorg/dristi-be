"""Tests for the import_pincodes management command."""

import json
import os
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import AdditionalAttribute
from apps.locations.models import Location
from apps.locations.tests.factories import make_country, make_district, make_state
from apps.users.models import User

HEADER = (
    "circlename,regionname,divisionname,officename,pincode,officetype,delivery,district,statename"
)


def office(pincode, district, state="KARNATAKA", office_type="B.O", name="Office"):
    """Return one post-office CSV row."""
    return f"Circle,Region,Division,{name},{pincode},{office_type},Delivery,{district},{state}"


class ImportPincodesTests(TestCase):
    """import_pincodes chooses a district per pincode and saves pincode locations."""

    def setUp(self):
        """Create India -> Karnataka -> two Bengaluru districts."""
        india = make_country()
        self.karnataka = make_state(parent=india, code="IN_KA", name="Karnataka", short_name="KA")
        self.urban = make_district(
            parent=self.karnataka, code="IN_KA_BLR_URBAN", name="Bengaluru Urban"
        )
        self.rural = make_district(
            parent=self.karnataka, code="IN_KA_BLR_RURAL", name="Bengaluru Rural"
        )

    def write(self, content, suffix=".csv"):
        """Write ``content`` to a temporary file and return its path."""
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
        with handle:
            handle.write(content)
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def csv(self, *rows):
        """Write a directory CSV with ``rows`` and return its path."""
        return self.write("\n".join([HEADER, *rows]) + "\n")

    def run_import(self, path, *args):
        """Run the command and return its output."""
        out = StringIO()
        call_command("import_pincodes", path, *args, stdout=out)
        return out.getvalue()

    def parent_code(self, pincode):
        """Return the parent code of the pincode location."""
        return Location.objects.get(code=f"PIN_{pincode}").parent.code

    def test_creates_pincode_under_matching_district(self):
        self.run_import(self.csv(office("560001", "BENGALURU URBAN", office_type="H.O")))

        location = Location.objects.get(code="PIN_560001")
        self.assertEqual(location.name, "560001")
        self.assertEqual(location.location_type, Location.LocationType.PINCODE)
        self.assertEqual(location.parent, self.urban)

    def test_post_offices_of_one_pincode_make_one_location(self):
        self.run_import(
            self.csv(office("560001", "Bengaluru Urban"), office("560001", "Bengaluru Urban"))
        )

        self.assertEqual(Location.objects.filter(code="PIN_560001").count(), 1)

    def test_split_pincode_goes_to_district_with_most_offices(self):
        self.run_import(
            self.csv(
                office("562106", "BENGALURU RURAL", office_type="S.O"),
                office("562106", "BENGALURU URBAN"),
                office("562106", "BENGALURU URBAN"),
            )
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_URBAN")

    def test_tie_goes_to_district_with_higher_ranked_office(self):
        self.run_import(
            self.csv(
                office("562106", "BENGALURU URBAN", office_type="B.O"),
                office("562106", "BENGALURU RURAL", office_type="S.O"),
            )
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_RURAL")

    def test_full_tie_goes_to_first_district_by_name(self):
        self.run_import(
            self.csv(office("562106", "BENGALURU URBAN"), office("562106", "BENGALURU RURAL"))
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_RURAL")

    def test_split_pincodes_listed_at_verbosity_two(self):
        path = self.csv(office("562106", "BENGALURU URBAN"), office("562106", "BENGALURU RURAL"))
        out = StringIO()
        call_command("import_pincodes", path, verbosity=2, stdout=out)

        self.assertIn("562106 spans several districts", out.getvalue())

    def test_matches_state_short_name(self):
        self.run_import(self.csv(office("560001", "Bengaluru Urban", state="ka")))

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")

    def test_unmatched_district_is_reported_and_skipped(self):
        output = self.run_import(self.csv(office("560001", "BANGALORE")))

        self.assertFalse(Location.objects.filter(code="PIN_560001").exists())
        self.assertIn("No active district location for KARNATAKA / BANGALORE", output)

    def test_alias_maps_csv_spelling_to_district(self):
        aliases = self.write(
            json.dumps({"KARNATAKA / BANGALORE": "IN_KA_BLR_URBAN"}), suffix=".json"
        )
        self.run_import(self.csv(office("560001", "BANGALORE")), "--aliases", aliases)

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")

    def test_alias_to_unknown_district_fails(self):
        aliases = self.write(json.dumps({"KARNATAKA / BANGALORE": "NOPE"}), suffix=".json")

        with self.assertRaises(CommandError):
            self.run_import(self.csv(office("560001", "BANGALORE")), "--aliases", aliases)

    def test_invalid_pincode_rows_are_skipped_and_reported(self):
        output = self.run_import(
            self.csv(office("056000", "BENGALURU URBAN"), office("560001", "BENGALURU URBAN"))
        )

        self.assertEqual(
            list(
                Location.objects.filter(location_type=Location.LocationType.PINCODE).values_list(
                    "name", flat=True
                )
            ),
            ["560001"],
        )
        self.assertIn("1 rows with an invalid pincode (e.g. '056000')", output)

    def test_file_without_usable_rows_fails(self):
        # A spreadsheet export that turned pincodes into numbers.
        with self.assertRaisesMessage(CommandError, "No usable rows"):
            self.run_import(self.csv(office("560001.0", "BENGALURU URBAN")))

    def test_reimport_keeps_existing_parent_without_update(self):
        self.run_import(self.csv(office("560001", "BENGALURU RURAL")))

        self.run_import(self.csv(office("560001", "BENGALURU URBAN")))

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_RURAL")

    def test_reimport_with_update_repoints_parent(self):
        self.run_import(self.csv(office("560001", "BENGALURU RURAL")))

        self.run_import(self.csv(office("560001", "BENGALURU URBAN")), "--update")

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")

    def test_dry_run_saves_nothing(self):
        output = self.run_import(self.csv(office("560001", "BENGALURU URBAN")), "--dry-run")

        self.assertFalse(Location.objects.filter(code="PIN_560001").exists())
        self.assertIn("Dry run: would have created 1", output)

    def test_accepts_older_header_names(self):
        path = self.write(
            "officename,pincode,officeType,Districtname,statename\n"
            "Office,560001,S.O,Bengaluru Urban,KARNATAKA\n"
        )
        self.run_import(path)

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")

    def test_missing_column_fails(self):
        path = self.write("officename,pincode,statename\nOffice,560001,KARNATAKA\n")

        with self.assertRaises(CommandError):
            self.run_import(path)

    def test_missing_file_fails(self):
        with self.assertRaises(CommandError):
            self.run_import("/nonexistent/pincodes.csv")

    def test_ancestors_endpoint_returns_district_and_state(self):
        self.run_import(self.csv(office("560001", "BENGALURU URBAN")))

        response = self.client.get(reverse("location-by-code-ancestors", args=["PIN_560001"]))

        self.assertEqual(response.status_code, 200)
        types = {row["location_type"]: row["name"] for row in response.json()["data"]}
        self.assertEqual(
            types, {"country": "India", "state": "Karnataka", "district": "Bengaluru Urban"}
        )

    def test_spellings_of_one_district_count_together(self):
        self.run_import(
            self.csv(
                office("562106", "Bengaluru Urban"),
                office("562106", "Bengaluru Urban"),
                office("562106", "BENGALURU URBAN"),
                office("562106", "BENGALURU RURAL"),
                office("562106", "BENGALURU RURAL"),
            )
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_URBAN")

    def test_aliased_spelling_counts_with_its_district(self):
        aliases = self.write(
            json.dumps({"KARNATAKA / BANGALORE": "IN_KA_BLR_URBAN"}), suffix=".json"
        )
        self.run_import(
            self.csv(
                office("562106", "BANGALORE"),
                office("562106", "BENGALURU URBAN"),
                office("562106", "BENGALURU RURAL"),
                office("562106", "BENGALURU RURAL"),
                office("562106", "BANGALORE"),
            ),
            "--aliases",
            aliases,
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_URBAN")

    def test_inactive_district_is_never_chosen(self):
        make_district(
            parent=self.karnataka, code="A_OLD_URBAN", name="Bengaluru Urban", is_active=False
        )

        self.run_import(self.csv(office("560001", "BENGALURU URBAN")))

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")

    def test_name_matching_two_active_districts_is_reported_and_skipped(self):
        make_district(
            parent=self.karnataka, code="IN_KA_OTHER", name="Other", short_name="Bengaluru Urban"
        )

        output = self.run_import(self.csv(office("560001", "BENGALURU URBAN")))

        self.assertFalse(Location.objects.filter(code="PIN_560001").exists())
        self.assertIn("Several active districts match KARNATAKA / BENGALURU URBAN", output)

    def test_po_counts_as_a_sub_office(self):
        self.run_import(
            self.csv(
                office("562106", "BENGALURU URBAN", office_type="BO"),
                office("562106", "BENGALURU RURAL", office_type="PO"),
            )
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_RURAL")

    def test_matched_minority_is_used_when_majority_is_unmatched(self):
        output = self.run_import(
            self.csv(
                office("562106", "UNKNOWN"),
                office("562106", "UNKNOWN"),
                office("562106", "BENGALURU RURAL"),
            )
        )

        self.assertEqual(self.parent_code("562106"), "IN_KA_BLR_RURAL")
        self.assertIn("No active district location for KARNATAKA / UNKNOWN (2 offices", output)

    def test_code_held_by_another_type_is_reported_not_crashed(self):
        make_district(parent=self.karnataka, code="PIN_560001", name="Odd")

        output = self.run_import(
            self.csv(office("560001", "BENGALURU URBAN"), office("560002", "BENGALURU URBAN"))
        )

        self.assertIn("PIN_560001 is already used by a district location", output)
        self.assertEqual(self.parent_code("560002"), "IN_KA_BLR_URBAN")

    def test_file_that_is_not_utf8_fails_cleanly(self):
        path = self.write("")
        with open(path, "wb") as handle:
            handle.write((HEADER + "\n" + office("560001", "MA\xcfSUR")).encode("cp1252"))

        with self.assertRaisesMessage(CommandError, "Cannot read"):
            self.run_import(path)

    def test_aliases_must_be_an_object(self):
        aliases = self.write(json.dumps(["KARNATAKA / BANGALORE"]), suffix=".json")

        with self.assertRaisesMessage(CommandError, "must be a JSON object"):
            self.run_import(self.csv(office("560001", "BANGALORE")), "--aliases", aliases)

    def test_alias_key_with_too_many_parts_fails(self):
        aliases = self.write(json.dumps({"A / B / C": "IN_KA_BLR_URBAN"}), suffix=".json")

        with self.assertRaisesMessage(CommandError, "must look like"):
            self.run_import(self.csv(office("560001", "BANGALORE")), "--aliases", aliases)

    def test_unused_bad_alias_still_fails(self):
        aliases = self.write(json.dumps({"KERALA / NOWHERE": "NOPE"}), suffix=".json")

        with self.assertRaisesMessage(CommandError, "NOPE"):
            self.run_import(self.csv(office("560001", "BENGALURU URBAN")), "--aliases", aliases)

    def test_state_alias_maps_every_district_of_that_state(self):
        aliases = self.write(json.dumps({"KARNATAKA STATE": "IN_KA"}), suffix=".json")

        self.run_import(
            self.csv(office("560001", "BENGALURU URBAN", state="KARNATAKA STATE")),
            "--aliases",
            aliases,
        )

        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")

    def test_differing_pincodes_are_reported_without_update(self):
        self.run_import(self.csv(office("560001", "BENGALURU RURAL")))

        out = StringIO()
        call_command(
            "import_pincodes",
            self.csv(office("560001", "BENGALURU URBAN")),
            verbosity=2,
            stdout=out,
        )

        self.assertIn("1 existing pincodes are under a different district", out.getvalue())
        self.assertIn(
            "560001: stored under IN_KA_BLR_RURAL, CSV now chooses IN_KA_BLR_URBAN", out.getvalue()
        )

    def test_update_keeps_admin_edits_unless_overwritten(self):
        self.run_import(self.csv(office("560001", "BENGALURU RURAL")))
        admin = User.objects.create_user(
            mobile_number="+919000000001", name="Admin", email="admin@example.com", password="x"
        )
        Location.objects.filter(code="PIN_560001").update(updated_by=admin)
        newer = self.csv(office("560001", "BENGALURU URBAN"))

        output = self.run_import(newer, "--update")
        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_RURAL")
        self.assertIn("1 pincodes edited by an admin were kept", output)

        self.run_import(newer, "--update", "--overwrite-edits")
        location = Location.objects.get(code="PIN_560001")
        self.assertEqual(location.parent.code, "IN_KA_BLR_URBAN")
        self.assertIsNone(location.updated_by)

    def test_overwrite_edits_needs_update(self):
        with self.assertRaisesMessage(CommandError, "only applies with --update"):
            self.run_import(self.csv(office("560001", "BENGALURU URBAN")), "--overwrite-edits")

    def test_pincodes_missing_from_the_csv_are_reported(self):
        self.run_import(
            self.csv(office("560001", "BENGALURU URBAN"), office("560002", "BENGALURU URBAN"))
        )

        output = self.run_import(self.csv(office("560001", "BENGALURU URBAN")))

        self.assertIn("1 pincode locations are not in this CSV", output)
        self.assertTrue(Location.objects.filter(code="PIN_560002").exists())

    def test_new_pincodes_get_additional_attribute_defaults(self):
        AdditionalAttribute.objects.create(
            content_type=ContentType.objects.get_for_model(Location),
            name="lgd_code",
            data_type="integer",
            is_nullable=False,
            default_value=0,
        )

        self.run_import(self.csv(office("560001", "BENGALURU URBAN")))

        self.assertEqual(
            Location.objects.get(code="PIN_560001").additional_attributes, {"lgd_code": 0}
        )

    def test_inactive_pincode_does_not_prefill(self):
        self.run_import(self.csv(office("560001", "BENGALURU URBAN")))
        url = reverse("location-by-code-ancestors", args=["PIN_560001"])

        self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 200)
        Location.objects.filter(code="PIN_560001").update(is_active=False)
        self.assertEqual(self.client.get(url, {"is_active": "true"}).status_code, 404)

    def test_pincode_under_inactive_district_does_not_prefill(self):
        self.run_import(self.csv(office("560001", "BENGALURU URBAN")))
        Location.objects.filter(code="IN_KA_BLR_URBAN").update(is_active=False)

        response = self.client.get(
            reverse("location-by-code-ancestors", args=["PIN_560001"]), {"is_active": "true"}
        )

        self.assertEqual(response.status_code, 404)

    def test_na_rows_are_skipped_as_missing_names(self):
        output = self.run_import(
            self.csv(office("560001", "NA", state="NA"), office("560002", "BENGALURU URBAN"))
        )

        self.assertIn("1 rows with no state or district", output)
        self.assertNotIn("NA / NA", output)

    def test_create_districts_adds_missing_states_and_districts(self):
        output = self.run_import(
            self.csv(
                office("570001", "MYSURU"),
                office("682001", "ERNAKULAM", state="KERALA"),
                office("682002", "Ernakulam", state="KERALA"),
                office("560001", "BENGALURU URBAN"),
            ),
            "--create-districts",
        )

        kerala = Location.objects.get(code="IN_KERALA")
        self.assertEqual(
            (kerala.name, kerala.location_type, kerala.parent.code),
            ("Kerala", Location.LocationType.STATE, "IN"),
        )
        # Karnataka already exists, so Mysuru goes under it; Ernakulam is created once.
        self.assertEqual(self.parent_code("570001"), "IN_KA_MYSURU")
        self.assertEqual(Location.objects.get(code="IN_KA_MYSURU").name, "Mysuru")
        self.assertEqual(self.parent_code("682001"), "IN_KERALA_ERNAKULAM")
        self.assertEqual(self.parent_code("682002"), "IN_KERALA_ERNAKULAM")
        self.assertEqual(self.parent_code("560001"), "IN_KA_BLR_URBAN")
        self.assertIn("Created 1 states and 2 districts.", output)
        self.assertNotIn("No active district location", output)

    def test_create_districts_dry_run_saves_nothing(self):
        output = self.run_import(
            self.csv(office("682001", "ERNAKULAM", state="KERALA")),
            "--create-districts",
            "--dry-run",
        )

        self.assertIn("Would create 1 states and 1 districts.", output)
        self.assertIn("Dry run: would have created 1", output)
        self.assertFalse(Location.objects.filter(code__startswith="IN_KERALA").exists())
        self.assertFalse(Location.objects.filter(code="PIN_682001").exists())

    def test_create_districts_keeps_codes_within_the_field(self):
        state = "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"
        self.run_import(
            self.csv(office("396230", "DADRA AND NAGAR HAVELI", state=state)),
            "--create-districts",
        )

        district = Location.objects.get(code=Location.objects.get(code="PIN_396230").parent.code)
        self.assertLessEqual(len(district.code), 50)
        self.assertEqual(district.name, "Dadra And Nagar Haveli")
        self.assertEqual(district.parent.name, "The Dadra And Nagar Haveli And Daman And Diu")

    def test_create_districts_creates_india_when_there_is_no_country(self):
        # Children first: a parent cannot be deleted while it has children.
        for location_type in ("district", "state", "country"):
            Location.objects.filter(location_type=location_type).delete()

        self.run_import(
            self.csv(office("682001", "ERNAKULAM", state="KERALA")), "--create-districts"
        )

        self.assertEqual(
            Location.objects.get(code="PIN_682001").get_full_name(),
            "India / Kerala / Ernakulam / 682001",
        )

    def test_create_districts_refuses_several_countries(self):
        Location.objects.create(
            code="NP", name="Nepal", location_type=Location.LocationType.COUNTRY
        )

        with self.assertRaisesMessage(CommandError, "exactly one active country"):
            self.run_import(
                self.csv(office("682001", "ERNAKULAM", state="KERALA")), "--create-districts"
            )

    def test_without_create_districts_nothing_is_created(self):
        self.run_import(self.csv(office("682001", "ERNAKULAM", state="KERALA")))

        self.assertFalse(Location.objects.filter(code__startswith="IN_KERALA").exists())


class DefaultDataDirTests(TestCase):
    """With no path, the CSV and aliases come from data/pincodes/ under BASE_DIR."""

    def setUp(self):
        """Point BASE_DIR at an empty temporary project with a Karnataka district."""
        india = make_country()
        karnataka = make_state(parent=india, code="IN_KA", name="Karnataka", short_name="KA")
        make_district(parent=karnataka, code="IN_KA_BLR_URBAN", name="Bengaluru Urban")
        base = tempfile.TemporaryDirectory()
        self.addCleanup(base.cleanup)
        self.base_dir = Path(base.name)
        self.folder = self.base_dir / "data" / "pincodes"
        self.folder.mkdir(parents=True)
        settings_override = override_settings(BASE_DIR=self.base_dir)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def run_default(self, *args):
        """Run the command with no CSV path and return its output."""
        out = StringIO()
        call_command("import_pincodes", *args, stdout=out)
        return out.getvalue()

    def test_missing_default_csv_says_where_to_put_it(self):
        with self.assertRaisesMessage(
            CommandError, str(self.folder / "all_india_pincode_directory.csv")
        ):
            self.run_default()

    def test_default_csv_is_imported(self):
        (self.folder / "all_india_pincode_directory.csv").write_text(
            "\n".join([HEADER, office("560001", "BENGALURU URBAN")]) + "\n", encoding="utf-8"
        )

        output = self.run_default()

        self.assertIn("Reading", output)
        self.assertTrue(Location.objects.filter(code="PIN_560001").exists())

    def test_default_aliases_are_used_when_present(self):
        (self.folder / "all_india_pincode_directory.csv").write_text(
            "\n".join([HEADER, office("560001", "BANGALORE")]) + "\n", encoding="utf-8"
        )
        (self.folder / "aliases.json").write_text(
            json.dumps({"KARNATAKA / BANGALORE": "IN_KA_BLR_URBAN"}), encoding="utf-8"
        )

        output = self.run_default()

        self.assertIn("Using aliases from", output)
        self.assertEqual(Location.objects.get(code="PIN_560001").parent.code, "IN_KA_BLR_URBAN")
