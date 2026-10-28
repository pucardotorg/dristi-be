"""Load pincodes as ``pincode`` locations under their districts.

The source is India Post's "All India Pincode Directory" CSV (data.gov.in),
which has one row per post office. Each office's state and district names are
first matched to an active district location; then each pincode becomes one
location, coded ``PIN_<pincode>``, whose parent is the matched district
holding most of its offices. Ties go to the district with the higher-ranked
office (head, then sub, then branch), then to the district name.

Names are matched case-insensitively against the ``name`` or ``short_name`` of
active district locations and their states. Names the CSV spells differently
are mapped with ``--aliases``, a JSON object whose keys are either a CSV state
(mapped to a state code) or ``"<CSV STATE> / <CSV DISTRICT>"`` (mapped to a
district code).

A pincode that already exists keeps its parent unless ``--update`` is given.
Even then, a pincode an admin has edited (``updated_by`` set) is left alone
unless ``--overwrite-edits`` is also given, so manual corrections survive a
re-import. Rows the import repoints have ``updated_by`` cleared: an empty
``updated_by`` means the row is as the import left it.

``--create-districts`` first creates every state and district the CSV names
that matches nothing, under the one country location (India is created if
there is none), so an empty database can be loaded in one run. Their names are
the CSV's, in title case when the CSV has them in capitals; their codes are
generated (``IN_KARNATAKA``, ``IN_KARNATAKA_MYSURU``). A dry run rolls back
everything, these included.

With no CSV path the files are read from ``data/pincodes/`` under ``src/``, so
loading an environment is: put the CSV there and run ``manage.py
import_pincodes``. See that folder's README.
"""

import copy
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict

from cachalot.api import cachalot_disabled
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.address.models import PINCODE_REGEX
from apps.locations.models import Location

PINCODE_RE = re.compile(PINCODE_REGEX)
CODE_PREFIX = "PIN_"
ALIAS_SEPARATOR = "/"
# How many examples of skipped values to print.
SAMPLE_SIZE = 5
# Where the files are looked for when no path is given, relative to src/.
DATA_DIR = ("data", "pincodes")
DEFAULT_CSV = "all_india_pincode_directory.csv"
DEFAULT_ALIASES = "aliases.json"
# The directory writes a missing state or district as "NA".
MISSING_NAMES = {"na"}
# Created when --create-districts finds no country location.
DEFAULT_COUNTRY = {"code": "IN", "name": "India", "short_name": "IN"}

# Header names differ between releases of the directory.
COLUMNS = {
    "pincode": ("pincode",),
    "district": ("district", "districtname"),
    "state": ("statename", "state"),
    "office_type": ("officetype",),
}
# Head, sub and branch offices. Older releases write sub offices as "S.O",
# newer ones as "PO".
OFFICE_RANK = {"HO": 3, "SO": 2, "PO": 2, "BO": 1}


def normalize(value):
    """Return ``value`` casefolded with whitespace collapsed, for matching."""
    return " ".join(value.split()).casefold()


def pincode_code(pincode):
    """Return the location code for ``pincode``."""
    return f"{CODE_PREFIX}{pincode}"


def data_dir():
    """Return the directory the CSV and aliases are read from by default."""
    return settings.BASE_DIR.joinpath(*DATA_DIR)


def location_names(location):
    """Return the normalized names a location can be matched by."""
    return {normalize(name) for name in (location.name, location.short_name) if name}


class Command(BaseCommand):
    """Import pincodes from the India Post directory CSV."""

    help = "Create a pincode location under its district for every pincode in the CSV."

    def add_arguments(self, parser):
        """Register the CSV path and options."""
        folder = "/".join(DATA_DIR)
        parser.add_argument(
            "csv_path",
            nargs="?",
            help=f"All India Pincode Directory CSV (default: {folder}/{DEFAULT_CSV}).",
        )
        parser.add_argument(
            "--aliases",
            help='JSON object mapping a CSV state to a state code, or "STATE / DISTRICT" '
            f"to a district code (default: {folder}/{DEFAULT_ALIASES}, if present).",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Repoint existing pincodes whose chosen district has changed.",
        )
        parser.add_argument(
            "--overwrite-edits",
            action="store_true",
            help="With --update, also repoint pincodes an admin has edited.",
        )
        parser.add_argument(
            "--create-districts",
            action="store_true",
            help="First create the states and districts the CSV names that match nothing.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would change without saving."
        )

    def handle(self, *args, **options):
        """Read the CSV, choose a district per pincode and save the locations."""
        if options["overwrite_edits"] and not options["update"]:
            raise CommandError("--overwrite-edits only applies with --update.")
        csv_path = options["csv_path"] or self._default_csv()
        aliases_path = options["aliases"] or self._default_aliases()
        aliases = read_aliases(aliases_path)
        resolver = DistrictResolver(aliases)
        offices, skipped = self._read_offices(csv_path)
        if not offices:
            raise CommandError(
                f"No usable rows in {csv_path}: {self._describe_skipped(skipped)}. "
                "Check the file is the comma-separated directory with unmodified pincodes."
            )
        # One transaction, so a dry run can roll back created districts too.
        with transaction.atomic(), cachalot_disabled():
            created = ([], [])
            if options["create_districts"]:
                names = {(state, district) for _pincode, state, district in offices}
                created = create_missing_districts(names, resolver)
                resolver = DistrictResolver(aliases)
            self._place(offices, skipped, resolver, created, options)
            if options["dry_run"]:
                transaction.set_rollback(True)

    def _place(self, offices, skipped, resolver, created, options):
        """Choose a district per pincode, save the pincodes and report."""
        by_pincode = defaultdict(dict)  # pincode -> {district pk: [count, rank, district]}
        unmatched, ambiguous = Counter(), Counter()
        for (pincode, state, district), (count, rank) in offices.items():
            location, problem = resolver.resolve(state, district)
            if location is None:
                (ambiguous if problem == "ambiguous" else unmatched)[(state, district)] += count
                continue
            entry = by_pincode[pincode].setdefault(location.pk, [0, 0, location])
            entry[0] += count
            entry[1] = max(entry[1], rank)
        chosen = {pincode: choose_district(found) for pincode, found in by_pincode.items()}
        split = {pincode: found for pincode, found in by_pincode.items() if len(found) > 1}
        not_placed = {pincode for pincode, _, _ in offices} - chosen.keys()

        result = self._save(chosen, options)

        verbose = options["verbosity"] >= 2
        self._report_created(created, verbose, options["dry_run"])
        if skipped:
            self._warn(f"Skipped {self._describe_skipped(skipped)}.")
        self._report_names(unmatched, "No active district location for", "unmatched")
        self._report_names(ambiguous, "Several active districts match", "ambiguous")
        for code, location_type in result["conflicts"]:
            self._warn(f"{code} is already used by a {location_type} location; not imported.")
        if verbose:
            self._report_split(split)
            for pincode, (current, new) in sorted(result["differs"].items()):
                self.stdout.write(f"{pincode}: stored under {current}, CSV now chooses {new}")
            for code in sorted(result["missing"]):
                self.stdout.write(f"{code} is not in this CSV")
        self._report_counts(result, split, not_placed, options)

    def _report_created(self, created, verbose, dry_run):
        """Say how many states and districts --create-districts made, listing them at -v 2."""
        states, districts = created
        if not (states or districts):
            return
        verb = "Would create" if dry_run else "Created"
        self.stdout.write(f"{verb} {len(states)} states and {len(districts)} districts.")
        if verbose:
            for location in [*states, *districts]:
                self.stdout.write(f"  {location.code}: {location.name}")

    def _default_csv(self):
        """Return the CSV in the data directory, or explain where to put it."""
        path = data_dir() / DEFAULT_CSV
        if not path.exists():
            raise CommandError(
                f"No CSV given and none at {path}. Download the All India Pincode Directory "
                "from https://www.data.gov.in/catalog/all-india-pincode-directory and save it "
                f"there as {DEFAULT_CSV} (see {'/'.join(DATA_DIR)}/README.md), or pass its path."
            )
        self.stdout.write(f"Reading {path}")
        return path

    def _default_aliases(self):
        """Return the aliases file in the data directory, if there is one."""
        path = data_dir() / DEFAULT_ALIASES
        if not path.exists():
            return None
        self.stdout.write(f"Using aliases from {path}")
        return path

    def _read_offices(self, path):
        """Return ``{(pincode, state, district): [offices, best rank]}`` and skipped rows."""
        offices = defaultdict(lambda: [0, 0])
        skipped = {"pincode": [], "name": 0}
        try:
            with open(path, newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                columns = self._columns(reader.fieldnames or [])
                for row in reader:
                    pincode = (row[columns["pincode"]] or "").strip()
                    state = " ".join((row[columns["state"]] or "").split())
                    district = " ".join((row[columns["district"]] or "").split())
                    if not PINCODE_RE.match(pincode):
                        skipped["pincode"].append(pincode)
                        continue
                    if (
                        not state
                        or not district
                        or {normalize(state), normalize(district)} & MISSING_NAMES
                    ):
                        skipped["name"] += 1
                        continue
                    office_type = row[columns["office_type"]] if columns["office_type"] else ""
                    rank = OFFICE_RANK.get(re.sub(r"[^A-Z]", "", (office_type or "").upper()), 0)
                    entry = offices[(pincode, state, district)]
                    entry[0] += 1
                    entry[1] = max(entry[1], rank)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from exc
        return offices, skipped

    def _columns(self, fieldnames):
        """Map each needed column to its header in this CSV."""
        headers = {normalize(name).replace(" ", ""): name for name in fieldnames}
        columns = {}
        for key, candidates in COLUMNS.items():
            columns[key] = next((headers[c] for c in candidates if c in headers), None)
            if columns[key] is None and key != "office_type":
                raise CommandError(
                    f"CSV has no {' or '.join(candidates)} column. "
                    "Check the file is comma-separated with the directory's header row."
                )
        return columns

    @transaction.atomic
    def _save(self, chosen, options):
        """Create or repoint pincode locations and return what happened."""
        # Rows coded PIN_* of any type, since codes are unique across all types,
        # and every pincode row, to report the ones this CSV no longer has.
        existing = {
            location.code: location
            for location in Location.objects.filter(
                Q(code__startswith=CODE_PREFIX) | Q(location_type=Location.LocationType.PINCODE)
            ).only("id", "code", "location_type", "parent_id", "updated_by_id")
        }
        defaults = self._attribute_defaults()
        now = timezone.now()
        result = {
            "created": [],
            "repointed": [],
            "unchanged": 0,
            "differs": {},
            "edited": [],
            "conflicts": [],
            "missing": [],
        }
        for pincode, district in chosen.items():
            location = existing.get(pincode_code(pincode))
            if location is None:
                result["created"].append(
                    Location(
                        code=pincode_code(pincode),
                        name=pincode,
                        short_name=pincode,
                        location_type=Location.LocationType.PINCODE,
                        parent=district,
                        additional_attributes=copy.deepcopy(defaults),
                    )
                )
            elif location.location_type != Location.LocationType.PINCODE:
                result["conflicts"].append((location.code, location.location_type))
            elif location.parent_id == district.pk:
                result["unchanged"] += 1
            elif not options["update"]:
                result["differs"][pincode] = (location.parent_id, district.code)
            elif location.updated_by_id and not options["overwrite_edits"]:
                result["edited"].append(location.code)
            else:
                location.parent = district
                location.updated_by = None
                # bulk_update skips auto_now, so stamp the change by hand.
                location.updated_at = now
                result["repointed"].append(location)

        parent_codes = dict(
            Location.objects.filter(
                pk__in={parent_id for parent_id, _ in result["differs"].values()}
            ).values_list("pk", "code")
        )
        result["differs"] = {
            pincode: (parent_codes.get(parent_id, str(parent_id)), new)
            for pincode, (parent_id, new) in result["differs"].items()
        }

        imported = {pincode_code(pincode) for pincode in chosen}
        result["missing"] = [
            code
            for code, location in existing.items()
            if location.location_type == Location.LocationType.PINCODE and code not in imported
        ]

        if not options["dry_run"]:
            Location.objects.bulk_create(result["created"], batch_size=1000)
            Location.objects.bulk_update(
                result["repointed"], ["parent", "updated_by", "updated_at"], batch_size=1000
            )
        return result

    def _attribute_defaults(self):
        """Return the additional attributes a new pincode starts with.

        ``bulk_create`` skips ``save()``, so the defaults it would fill in are
        worked out once here instead.
        """
        try:
            return Location(
                location_type=Location.LocationType.PINCODE
            )._clean_additional_attributes()
        except ValidationError as exc:
            raise CommandError(
                f"Location has required additional attributes the import cannot set: {exc}"
            ) from exc

    def _describe_skipped(self, skipped):
        """Summarize the rows skipped for a bad pincode or a missing name."""
        bad = skipped["pincode"]
        parts = []
        if bad:
            sample = ", ".join(repr(value) for value in bad[:SAMPLE_SIZE])
            parts.append(f"{len(bad)} rows with an invalid pincode (e.g. {sample})")
        if skipped["name"]:
            parts.append(f"{skipped['name']} rows with no state or district")
        return "; ".join(parts) or "the file has no data rows"

    def _report_names(self, names, prefix, kind):
        """Warn about CSV state/district names that matched no single district."""
        hint = "add an alias" if kind == "unmatched" else "add an alias to choose one"
        for (state, district), count in sorted(names.items()):
            self._warn(
                f"{prefix} {state} / {district} ({count} offices skipped; {hint})",
            )

    def _report_split(self, split):
        """List pincodes whose offices sit in several districts, with office counts."""
        for pincode, found in sorted(split.items()):
            counts = ", ".join(
                f"{district.code}: {count}"
                for count, _rank, district in sorted(found.values(), key=lambda e: e[2].code)
            )
            self.stdout.write(f"{pincode} spans several districts ({counts})")

    def _report_counts(self, result, split, not_placed, options):
        """Print the summary line and what to do about rows left as they were."""
        if result["differs"]:
            self._warn(
                f"{len(result['differs'])} existing pincodes are under a different district than "
                "this CSV chooses; run with -v 2 to list them, or --update to repoint them."
            )
        if result["edited"]:
            self._warn(
                f"{len(result['edited'])} pincodes edited by an admin were kept; "
                "add --overwrite-edits to repoint them too."
            )
        if result["missing"]:
            self._warn(
                f"{len(result['missing'])} pincode locations are not in this CSV; "
                "run with -v 2 to list them, then review them in the admin."
            )
        prefix = "Dry run: would have " if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}created {len(result['created'])}, "
                f"repointed {len(result['repointed'])}, "
                f"left {result['unchanged']} unchanged; "
                f"{len(split)} span several districts; "
                f"{len(not_placed)} not placed (no matching district)."
            )
        )

    def _warn(self, message):
        """Write ``message`` as a warning."""
        self.stdout.write(self.style.WARNING(message))


def choose_district(found):
    """Return the district with most offices, then the best office, then by name."""
    _count, _rank, district = min(
        found.values(),
        key=lambda entry: (-entry[0], -entry[1], normalize(entry[2].name), entry[2].code),
    )
    return district


def read_aliases(path):
    """Return ``(state aliases, district aliases)`` read from the JSON file at ``path``.

    State aliases are keyed by normalized CSV state, district aliases by
    normalized ``(CSV state, CSV district)``; both map to location codes.
    """
    if not path:
        return {}, {}
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CommandError(f"Cannot read aliases from {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CommandError(f"Aliases in {path} must be a JSON object.")
    states, districts = {}, {}
    for key, code in raw.items():
        if not isinstance(code, str) or not code:
            raise CommandError(f"Alias {key!r} must map to a location code.")
        parts = [part.strip() for part in key.split(ALIAS_SEPARATOR)]
        if len(parts) == 1 and parts[0]:
            states[normalize(parts[0])] = code
        elif len(parts) == 2 and all(parts):
            districts[(normalize(parts[0]), normalize(parts[1]))] = code
        else:
            raise CommandError(f'Alias {key!r} must look like "STATE" or "STATE / DISTRICT".')
    return states, districts


def create_missing_districts(names, resolver):
    """Create the states and districts in ``names`` that resolve to nothing.

    ``names`` is a set of CSV ``(state, district)`` pairs. A pair that resolves,
    or matches several districts, is left alone. Returns the created
    ``(states, districts)``.
    """
    country = default_country()
    states = {}
    for state in Location.objects.filter(location_type=Location.LocationType.STATE, is_active=True):
        for name in location_names(state):
            states.setdefault(name, state)
    created_states, created_districts = [], []
    # Spellings differing only in case or spacing are one district.
    pairs = {
        (normalize(state), normalize(district)): (state, district) for state, district in names
    }
    for (state_key, _district_key), (state_name, district_name) in sorted(pairs.items()):
        location, problem = resolver.resolve(state_name, district_name)
        if location is not None or problem == "ambiguous":
            continue
        state = next(
            (states[n] for n in resolver.state_aliases.get(state_key, {state_key}) if n in states),
            None,
        )
        if state is None:
            state = Location.objects.create(
                code=new_code(country.code, state_name),
                name=display_name(state_name),
                location_type=Location.LocationType.STATE,
                parent=country,
            )
            states[state_key] = state
            created_states.append(state)
        created_districts.append(
            Location.objects.create(
                code=new_code(state.code, district_name),
                name=display_name(district_name),
                location_type=Location.LocationType.DISTRICT,
                parent=state,
            )
        )
    return created_states, created_districts


def default_country():
    """Return the one active country location, creating India when there is none."""
    countries = list(
        Location.objects.filter(location_type=Location.LocationType.COUNTRY, is_active=True)[:2]
    )
    if len(countries) > 1:
        raise CommandError(
            "--create-districts needs exactly one active country location; found several."
        )
    if countries:
        return countries[0]
    return Location.objects.create(location_type=Location.LocationType.COUNTRY, **DEFAULT_COUNTRY)


def display_name(name):
    """Return a CSV name for display: title case when the CSV wrote it in capitals."""
    return name.title() if name.isupper() else name


def new_code(prefix, name):
    """Return an unused location code ``<prefix>_<NAME>``.

    Shortened, with a hash of the full code for uniqueness, when too long for
    the field or already taken.
    """
    max_length = Location._meta.get_field("code").max_length
    slug = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "X"
    code = f"{prefix}_{slug}"
    if len(code) <= max_length and not Location.objects.filter(code=code).exists():
        return code
    suffix = hashlib.sha1(code.encode()).hexdigest()[:8].upper()
    return f"{code[: max_length - len(suffix) - 1].rstrip('_')}_{suffix}"


class DistrictResolver:
    """Find the active district location for a CSV state and district name."""

    def __init__(self, aliases):
        """Index active districts by state and district names, and check every alias."""
        state_aliases, district_aliases = aliases
        self.by_name = defaultdict(set)
        districts = Location.objects.filter(
            location_type=Location.LocationType.DISTRICT,
            is_active=True,
            parent__location_type=Location.LocationType.STATE,
        ).select_related("parent")
        for district in districts:
            for state_name in location_names(district.parent):
                for district_name in location_names(district):
                    self.by_name[(state_name, district_name)].add(district)

        bad = []
        states = {
            state.code: state
            for state in Location.objects.filter(
                code__in=state_aliases.values(), location_type=Location.LocationType.STATE
            )
        }
        # A state alias points the CSV spelling at the state's own names.
        self.state_aliases = {}
        for csv_state, code in state_aliases.items():
            if code in states:
                self.state_aliases[csv_state] = location_names(states[code])
            else:
                bad.append(code)
        found = {
            district.code: district
            for district in districts.filter(code__in=list(district_aliases.values()))
        }
        self.district_aliases = {}
        for key, code in district_aliases.items():
            if code in found:
                self.district_aliases[key] = found[code]
            else:
                bad.append(code)
        if bad:
            raise CommandError(
                f"Aliases name unknown or inactive locations: {', '.join(sorted(set(bad)))}."
            )

    def resolve(self, state, district):
        """Return ``(district location, None)``, or ``(None, "unmatched" | "ambiguous")``."""
        state_key, district_key = normalize(state), normalize(district)
        if (state_key, district_key) in self.district_aliases:
            return self.district_aliases[(state_key, district_key)], None
        candidates = set()
        for name in self.state_aliases.get(state_key, {state_key}):
            candidates |= self.by_name.get((name, district_key), set())
        if len(candidates) == 1:
            return next(iter(candidates)), None
        return None, "ambiguous" if candidates else "unmatched"
