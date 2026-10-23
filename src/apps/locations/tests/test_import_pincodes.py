"""Tests for the import_pincodes management command."""

import json
import os
import tempfile
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from apps.locations.models import Location
from apps.locations.tests.factories import make_country, make_district, make_state

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
        self.assertIn("No district location for KARNATAKA / BANGALORE", output)

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

    def test_invalid_pincode_rows_are_ignored(self):
        self.run_import(self.csv(office("056000", "BENGALURU URBAN")))

        self.assertFalse(
            Location.objects.filter(location_type=Location.LocationType.PINCODE).exists()
        )

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
