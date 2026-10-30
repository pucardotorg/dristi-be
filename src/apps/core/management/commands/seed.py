"""Seed initial reference data from TOML files (spec 0025).

One self-describing command loads locations, organizations, business rules,
configurations and CMS pages from human-readable TOML. Each file names its
target model in a ``[seed]`` header and lists ``[[rows]]``; the command matches
each row by the model's natural key and **inserts only the missing ones** —
existing rows are never touched (updates and deletes stay a manual admin task).

Relationships are resolved by a related row's natural key (its code): a
location's ``parent``, an organization's ``parent`` and ``jurisdictions``, a
page's ``categories``. An unresolved reference skips just that row. The whole
run is one transaction, so a failure (or ``--dry-run``) leaves the database
untouched.

    manage.py seed data/seed/kl/               # a directory of *.toml
    manage.py seed a.toml b.toml               # explicit files
    manage.py seed --list                      # show seedable models
"""

import tomllib
from pathlib import Path

from cachalot.api import cachalot_disabled
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction

from apps.core.seeding import specs  # noqa: F401  (import populates the registry)
from apps.core.seeding.registry import all_specs, lookup

# Values treated as "absent" for a nullable field or an optional key.
EMPTY = (None, "")
# Text-like fields TOML non-strings are stringified for (e.g. config_value).
TEXT_FIELDS = (models.CharField, models.TextField)


class RowError(Exception):
    """One row could not be seeded; the message explains why it was skipped."""


class Command(BaseCommand):
    """Insert initial reference data from TOML files or directories."""

    help = "Seed initial reference data from TOML files or directories (insert-only)."

    def add_arguments(self, parser):
        """Register the paths and options."""
        parser.add_argument("paths", nargs="*", help="TOML files or directories of them.")
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_models",
            help="Print the registered seedable models and exit.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without saving.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit non-zero (and commit nothing) if any row is skipped.",
        )

    def handle(self, *args, **options):
        """List the models, or read the files and insert the missing rows."""
        if options["list_models"]:
            self._list_models()
            return

        if not options["paths"]:
            raise CommandError("Give at least one TOML file or directory, or use --list.")

        files = self._collect_files(options["paths"])
        documents = [self._read_document(path) for path in files]
        # Group by model via each spec's load order, then by file name.
        documents.sort(key=lambda doc: (doc["spec"].order, str(doc["path"])))

        totals = {"created": 0, "unchanged": 0, "skipped": 0}
        committed = True
        # Disable the ORM query cache for the load: a bulk seed should not thrash
        # the cache, and this matches the import_pincodes command.
        with transaction.atomic(), cachalot_disabled():
            for document in documents:
                self._load(document, options, totals)
            # A dry run previews everything (relationships included) then rolls
            # back; a strict run with skips is all-or-nothing.
            if options["dry_run"] or (options["strict"] and totals["skipped"]):
                transaction.set_rollback(True)
                committed = False

        self._summary(totals, options, committed)
        if options["strict"] and totals["skipped"]:
            raise CommandError(
                f"{totals['skipped']} row(s) skipped; nothing was committed (--strict)."
            )

    # -- listing -----------------------------------------------------------

    def _list_models(self):
        """Print the registered seedable models in load order."""
        self.stdout.write("Seedable models (in load order):")
        for spec in all_specs():
            self.stdout.write(f"  {spec.model_label}  (key: {', '.join(spec.key)})")

    # -- collecting and reading files -------------------------------------

    def _collect_files(self, paths):
        """Expand each path (a directory loads its ``*.toml`` recursively)."""
        files = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                found = sorted(path.rglob("*.toml"))
                if not found:
                    self._warn(f"No .toml files under {path}")
                files.extend(found)
            elif path.is_file():
                files.append(path)
            else:
                raise CommandError(f"No such file or directory: {path}")
        if not files:
            raise CommandError("No .toml files to seed.")
        return files

    def _read_document(self, path):
        """Parse one TOML file into its spec, rows and natural key."""
        try:
            with open(path, "rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from exc

        header = data.get("seed")
        if not isinstance(header, dict) or not header.get("model"):
            raise CommandError(f"{path}: missing a [seed] table with a `model`.")
        spec = lookup(header["model"])
        if spec is None:
            known = ", ".join(s.model_label for s in all_specs())
            raise CommandError(f"{path}: unknown model {header['model']!r}. Registered: {known}.")

        rows = data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise CommandError(f"{path}: no [[rows]] to seed.")

        key = header.get("key")
        if key:
            key = (key,) if isinstance(key, str) else tuple(key)
        else:
            key = spec.key
        return {"path": path, "spec": spec, "rows": rows, "key": key}

    # -- loading ----------------------------------------------------------

    def _load(self, document, options, totals):
        """Insert the missing rows of one document and report its counts."""
        spec = document["spec"]
        model = spec.get_model()
        verbose = options["verbosity"] >= 2
        created = unchanged = skipped = 0
        for index, row in enumerate(document["rows"], start=1):
            try:
                if not isinstance(row, dict):
                    raise RowError("row is not a table")
                outcome, label = self._seed_row(model, spec, document["key"], row)
            except RowError as exc:
                skipped += 1
                self._warn(f"{document['path']} row {index}: skipped — {exc}")
                continue
            if outcome == "created":
                created += 1
                if verbose:
                    self.stdout.write(f"  + {spec.model_label} {label}")
            else:
                unchanged += 1

        totals["created"] += created
        totals["unchanged"] += unchanged
        totals["skipped"] += skipped
        self.stdout.write(
            f"{document['path']}: created {created}, unchanged {unchanged}, skipped {skipped}."
        )

    def _seed_row(self, model, spec, key, row):
        """Insert one row, or report it unchanged. Raise RowError to skip it."""
        unknown = set(row) - spec.allowed
        if unknown:
            raise RowError(f"unknown field(s): {', '.join(sorted(unknown))}")
        missing_key = [name for name in key if row.get(name) in EMPTY]
        if missing_key:
            raise RowError(f"missing key field(s): {', '.join(missing_key)}")
        label = ", ".join(f"{name}={row[name]}" for name in key)

        # Idempotency: a row with this natural key is left exactly as it is.
        if model.objects.filter(**{name: row[name] for name in key}).exists():
            return "unchanged", label

        # Resolve relationships first: an unresolved one skips the whole row,
        # so a half-built row is never saved.
        fk_values = self._resolve_fks(spec, row)
        m2m_values = self._resolve_m2ms(spec, row)

        instance = model()
        for name in spec.fields:
            if name in row:
                setattr(instance, name, self._coerce(model, name, row[name]))
        for name, obj in fk_values.items():
            setattr(instance, name, obj)

        try:
            instance.full_clean()
        except ValidationError as exc:
            raise RowError(self._describe(exc)) from exc

        instance.save()
        for name, objects in m2m_values.items():
            getattr(instance, name).set(objects)
        return "created", label

    def _resolve_fks(self, spec, row):
        """Resolve each foreign key in the row to its related object, by code."""
        resolved = {}
        for name, ref in spec.fk_by_code.items():
            value = row.get(name)
            if value in EMPTY:
                continue  # nullable / optional reference
            obj = ref.get_model().objects.filter(**{ref.key: value}).first()
            if obj is None:
                raise RowError(f"{name}: no {ref.model_label} with {ref.key}={value!r}")
            resolved[name] = obj
        return resolved

    def _resolve_m2ms(self, spec, row):
        """Resolve each many-to-many list of codes to its related objects."""
        resolved = {}
        for name, ref in spec.m2m_by_code.items():
            values = row.get(name)
            if values in EMPTY:
                continue
            if not isinstance(values, list):
                raise RowError(f"{name}: expected a list of {ref.key} values")
            objects, missing = [], []
            for value in values:
                obj = ref.get_model().objects.filter(**{ref.key: value}).first()
                (objects if obj is not None else missing).append(obj if obj else value)
            if missing:
                raise RowError(f"{name}: no {ref.model_label} with {ref.key} in {missing}")
            resolved[name] = objects
        return resolved

    def _coerce(self, model, name, value):
        """Coerce a TOML value to the field's type; raise RowError if it cannot."""
        if value is None:
            return value
        field = model._meta.get_field(name)
        # Text fields keep opaque strings: stringify non-strings (e.g. a numeric
        # config_value) so native TOML types are accepted.
        if isinstance(field, TEXT_FIELDS) and not isinstance(value, str):
            value = str(value)
        try:
            return field.to_python(value)
        except ValidationError as exc:
            raise RowError(self._describe(exc)) from exc

    # -- reporting --------------------------------------------------------

    def _summary(self, totals, options, committed):
        """Print the one-line run summary."""
        counts = (
            f"created {totals['created']}, unchanged {totals['unchanged']}, "
            f"skipped {totals['skipped']}"
        )
        if options["dry_run"]:
            message = f"Dry run: would have {counts}."
        elif not committed:
            message = f"Rolled back ({counts})."
        else:
            message = f"{counts}."
        style = self.style.WARNING if totals["skipped"] else self.style.SUCCESS
        self.stdout.write(style(message))

    def _describe(self, exc):
        """Render a ValidationError as a compact one-line message."""
        try:
            items = exc.message_dict
        except AttributeError:
            return "; ".join(exc.messages)
        return " | ".join(f"{field}: {'; '.join(msgs)}" for field, msgs in items.items())

    def _warn(self, message):
        """Write ``message`` as a warning."""
        self.stdout.write(self.style.WARNING(message))
