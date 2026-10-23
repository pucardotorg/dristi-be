"""Load pincodes as ``pincode`` locations under their districts.

The source is India Post's "All India Pincode Directory" CSV (data.gov.in),
which has one row per post office. Each pincode becomes one location, coded
``PIN_<pincode>``, whose parent is the district holding most of its post
offices; ties go to the district with the higher-ranked office (head, then
sub, then branch), then to the district name. Pincodes that span districts
are reported so an admin can repoint any that are wrong.

District and state names are matched case-insensitively against existing
district locations (``name`` or ``short_name``) under their state. Names the
CSV spells differently are mapped with ``--aliases``, a JSON file of
``{"<CSV STATE> / <CSV DISTRICT>": "<district location code>"}``.

Existing pincodes keep their parent unless ``--update`` is given, so manual
corrections survive a re-import.
"""

import csv
import json
import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.locations.models import Location

PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
CODE_PREFIX = "PIN_"
ALIAS_SEPARATOR = " / "

# Header names differ between releases of the directory.
COLUMNS = {
    "pincode": ("pincode",),
    "district": ("district", "districtname"),
    "state": ("statename", "state"),
    "office_type": ("officetype",),
}
OFFICE_RANK = {"HO": 3, "SO": 2, "BO": 1}


def normalize(value):
    """Return ``value`` casefolded with whitespace collapsed, for matching."""
    return " ".join(value.split()).casefold()


def pincode_code(pincode):
    """Return the location code for ``pincode``."""
    return f"{CODE_PREFIX}{pincode}"


class Command(BaseCommand):
    """Import pincodes from the India Post directory CSV."""

    help = "Create a pincode location under its district for every pincode in the CSV."

    def add_arguments(self, parser):
        """Register the CSV path and options."""
        parser.add_argument("csv_path", help="All India Pincode Directory CSV.")
        parser.add_argument(
            "--aliases",
            help='JSON file mapping "<CSV STATE> / <CSV DISTRICT>" to a district code.',
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Repoint existing pincodes whose chosen district has changed.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would change without saving."
        )

    def handle(self, *args, **options):
        """Read the CSV, choose a district per pincode and save the locations."""
        offices = self._read_offices(options["csv_path"])
        resolver = DistrictResolver(self._read_aliases(options["aliases"]))

        chosen = {}
        unmatched = Counter()
        split = {}
        for pincode, by_district in sorted(offices.items()):
            state, district = choose_district(by_district)
            if len(by_district) > 1:
                split[pincode] = by_district
            location = resolver.resolve(state, district)
            if location is None:
                unmatched[(state, district)] += 1
            else:
                chosen[pincode] = location

        created, updated, kept = self._save(chosen, options["update"], options["dry_run"])

        self._report_split(split, options["verbosity"])
        self._report_unmatched(unmatched)
        prefix = "Dry run: would have " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}created {created}, updated {updated}, kept {kept} pincodes; "
                f"{len(split)} span several districts; "
                f"{sum(unmatched.values())} skipped for unmatched districts."
            )
        )

    def _read_offices(self, path):
        """Return ``{pincode: {(state, district): [office count, best office rank]}}``."""
        offices = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        try:
            with open(path, newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                columns = self._columns(reader.fieldnames or [])
                for row in reader:
                    pincode = (row[columns["pincode"]] or "").strip()
                    state = " ".join((row[columns["state"]] or "").split())
                    district = " ".join((row[columns["district"]] or "").split())
                    if not PINCODE_RE.match(pincode) or not state or not district:
                        continue
                    office_type = row[columns["office_type"]] if columns["office_type"] else ""
                    rank = OFFICE_RANK.get(re.sub(r"[^A-Z]", "", (office_type or "").upper()), 0)
                    entry = offices[pincode][(state, district)]
                    entry[0] += 1
                    entry[1] = max(entry[1], rank)
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from exc
        return offices

    def _columns(self, fieldnames):
        """Map each needed column to its header in this CSV."""
        headers = {normalize(name).replace(" ", ""): name for name in fieldnames}
        columns = {}
        for key, candidates in COLUMNS.items():
            columns[key] = next((headers[c] for c in candidates if c in headers), None)
            if columns[key] is None and key != "office_type":
                raise CommandError(f"CSV has no {' or '.join(candidates)} column.")
        return columns

    def _read_aliases(self, path):
        """Return the alias map keyed by normalized (state, district)."""
        if not path:
            return {}
        try:
            with open(path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read aliases from {path}: {exc}") from exc
        aliases = {}
        for key, code in raw.items():
            state, sep, district = key.partition(ALIAS_SEPARATOR.strip())
            if not sep:
                raise CommandError(f'Alias {key!r} must look like "STATE / DISTRICT".')
            aliases[(normalize(state), normalize(district))] = code
        return aliases

    @transaction.atomic
    def _save(self, chosen, update, dry_run):
        """Create or repoint pincode locations; return (created, updated, kept)."""
        existing = {
            location.code: location
            for location in Location.objects.filter(location_type=Location.LocationType.PINCODE)
        }
        to_create, to_update = [], []
        kept = 0
        now = timezone.now()
        for pincode, district in chosen.items():
            location = existing.get(pincode_code(pincode))
            if location is None:
                to_create.append(
                    Location(
                        code=pincode_code(pincode),
                        name=pincode,
                        short_name=pincode,
                        location_type=Location.LocationType.PINCODE,
                        parent=district,
                    )
                )
            elif location.parent_id != district.pk and update:
                location.parent = district
                # bulk_update skips auto_now, so stamp the change by hand.
                location.updated_at = now
                to_update.append(location)
            else:
                kept += 1

        if not dry_run:
            Location.objects.bulk_create(to_create, batch_size=1000)
            Location.objects.bulk_update(to_update, ["parent", "updated_at"], batch_size=1000)
        return len(to_create), len(to_update), kept

    def _report_split(self, split, verbosity):
        """List pincodes spanning several districts, with office counts (verbosity 2)."""
        if verbosity < 2:
            return
        for pincode, by_district in split.items():
            counts = ", ".join(
                f"{state} / {district}: {count}"
                for (state, district), (count, _rank) in sorted(by_district.items())
            )
            self.stdout.write(f"{pincode} spans several districts ({counts})")

    def _report_unmatched(self, unmatched):
        """List CSV districts with no matching district location."""
        for (state, district), count in sorted(unmatched.items()):
            self.stdout.write(
                self.style.WARNING(
                    f"No district location for {state}{ALIAS_SEPARATOR}{district} "
                    f"({count} pincodes skipped)"
                )
            )


def choose_district(by_district):
    """Return the (state, district) with most offices, then best office, then by name."""
    return min(
        by_district,
        key=lambda key: (-by_district[key][0], -by_district[key][1], normalize(key[0]), key[1]),
    )


class DistrictResolver:
    """Find the district location for a CSV state and district name."""

    def __init__(self, aliases):
        """Index active and inactive districts by normalized state and district names."""
        self.aliases = aliases
        self.by_name = {}
        districts = Location.objects.filter(
            location_type=Location.LocationType.DISTRICT,
            parent__location_type=Location.LocationType.STATE,
        ).select_related("parent")
        for district in districts:
            state = district.parent
            for state_name in {state.name, state.short_name} - {""}:
                for district_name in {district.name, district.short_name} - {""}:
                    key = (normalize(state_name), normalize(district_name))
                    self.by_name.setdefault(key, district)
        self.by_code = {}

    def resolve(self, state, district):
        """Return the district location, or None when nothing matches."""
        key = (normalize(state), normalize(district))
        code = self.aliases.get(key)
        if code is None:
            return self.by_name.get(key)
        if code not in self.by_code:
            self.by_code[code] = Location.objects.filter(
                code=code, location_type=Location.LocationType.DISTRICT
            ).first()
        location = self.by_code[code]
        if location is None:
            raise CommandError(f"Alias for {state} / {district} names unknown district {code!r}.")
        return location
