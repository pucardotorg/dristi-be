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

from apps.core.models import cached_attribute_definitions
from apps.core.seeding import specs  # noqa: F401  (import populates the registry)
from apps.core.seeding.registry import all_specs, lookup

# Values treated as "absent" for a nullable field or an optional key.
EMPTY = (None, "")
# Rows read, validated and inserted together by a bulk spec.
BULK_BATCH_SIZE = 1000
# Scalar TOML values a natural key or code reference can take.
KEY_TYPES = (str, int)
# Text-like fields TOML non-strings are stringified for (e.g. config_value).
TEXT_FIELDS = (models.CharField, models.TextField)


def _values(rows, name):
    """Return the distinct, non-empty scalar values of ``name`` across ``rows``."""
    return {
        row.get(name)
        for row in rows
        if isinstance(row, dict) and isinstance(row.get(name), KEY_TYPES)
    } - set(EMPTY)


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
        # Group by model via each spec's load order; within one order, keep the
        # order the files were given (sort is stable), so a caller can control
        # dependent loads, e.g. states.toml before districts.toml before
        # pincodes.toml. Files from a directory keep their sorted-name order.
        documents.sort(key=lambda doc: doc["spec"].order)

        totals = {"created": 0, "unchanged": 0, "skipped": 0}
        committed = True
        # Disable the ORM query cache for the load: a bulk seed should not
        # thrash the cache with its many inserts and invalidations.
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
        verbose = options["verbosity"] >= 2
        bulk_ready = (
            len(document["key"]) == 1
            and not spec.m2m_by_code
            and not any(ref.natural_key for ref in spec.fk_by_code.values())
        )
        if spec.bulk and bulk_ready:
            created, unchanged, skipped = self._load_bulk(document, verbose)
        else:
            created, unchanged, skipped = self._load_rows(document, verbose)

        totals["created"] += created
        totals["unchanged"] += unchanged
        totals["skipped"] += skipped
        self.stdout.write(
            f"{document['path']}: created {created}, unchanged {unchanged}, skipped {skipped}."
        )

    def _load_rows(self, document, verbose):
        """Save the document's missing rows one at a time; return the counts."""
        spec = document["spec"]
        model = spec.get_model()
        created = unchanged = skipped = 0
        for index, row in enumerate(document["rows"], start=1):
            try:
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
        return created, unchanged, skipped

    def _load_bulk(self, document, verbose):
        """Insert the document's missing rows in batches; return the counts.

        Same outcome as ``_load_rows`` with a fixed number of queries per batch
        instead of several per row: existing keys and referenced rows are read
        once per batch, each row is validated in memory, and the batch is
        written with one ``bulk_create``. A row may reference one created
        earlier in the same file, in this batch or an earlier one.
        """
        spec = document["spec"]
        model = spec.get_model()
        (key,) = document["key"]
        rows = document["rows"]
        # Rows this file references, kept once created so later rows resolve them.
        referenced = {
            name: {self._key_value(ref.get_model(), ref.key, v) for v in _values(rows, name)}
            for name, ref in spec.fk_by_code.items()
        }
        resolved = {name: {} for name in spec.fk_by_code}
        seen = set()
        created = unchanged = skipped = 0
        with cached_attribute_definitions():
            for start in range(0, len(rows), BULK_BATCH_SIZE):
                batch = list(enumerate(rows[start : start + BULK_BATCH_SIZE], start=start + 1))
                existing = self._existing_keys(model, key, batch)
                self._fetch_references(spec, batch, resolved)
                pending = []
                for index, row in batch:
                    try:
                        instance = self._build_row(
                            model, spec, key, row, (existing, seen), resolved
                        )
                    except RowError as exc:
                        skipped += 1
                        self._warn(f"{document['path']} row {index}: skipped — {exc}")
                        continue
                    if instance is None:
                        unchanged += 1
                        continue
                    value = getattr(instance, key)
                    seen.add(value)
                    pending.append(instance)
                    for name, ref in spec.fk_by_code.items():
                        target = getattr(instance, ref.key, None)
                        if ref.get_model() is model and target in referenced[name]:
                            resolved[name][target] = instance
                    if verbose:
                        self.stdout.write(f"  + {spec.model_label} {key}={value}")
                model.objects.bulk_create(pending)
                created += len(pending)
        return created, unchanged, skipped

    def _existing_keys(self, model, key, batch):
        """Return the batch's key values that are already in the database."""
        values = _values((row for _, row in batch), key)
        return set(model.objects.filter(**{f"{key}__in": values}).values_list(key, flat=True))

    def _fetch_references(self, spec, batch, resolved):
        """Read the rows the batch references that are not resolved yet."""
        for name, ref in spec.fk_by_code.items():
            values = _values((row for _, row in batch), name)
            wanted = {self._key_value(ref.get_model(), ref.key, v) for v in values}
            wanted -= set(resolved[name])
            if wanted:
                related = ref.get_model().objects.filter(**{f"{ref.key}__in": wanted})
                for obj in related:
                    resolved[name][getattr(obj, ref.key)] = obj

    def _build_row(self, model, spec, key, row, known_keys, resolved):
        """Return an unsaved, validated instance, or None when the key exists.

        ``known_keys`` holds the keys already in the database and those created
        earlier in this file. Raise RowError to skip the row.
        """
        self._check_row(model, spec, (key,), row)
        if not isinstance(row[key], KEY_TYPES):
            raise RowError(f"{key}: expected a single value")
        value = self._key_value(model, key, row[key])
        if any(value in keys for keys in known_keys):
            return None
        instance = model()
        for name in spec.fields:
            if name in row:
                setattr(instance, name, self._coerce(model, name, row[name]))
        for name, ref in spec.fk_by_code.items():
            value = row.get(name)
            if value in EMPTY:
                continue
            obj = (
                resolved[name].get(self._key_value(ref.get_model(), ref.key, value))
                if isinstance(value, KEY_TYPES)
                else None
            )
            if obj is None:
                raise RowError(f"{name}: no {ref.model_label} with {ref.key}={value!r}")
            setattr(instance, name, obj)
        try:
            # Foreign keys were resolved above, possibly to a row created in
            # this batch and not saved yet, and keys already checked: skip the
            # per-row existence and uniqueness queries.
            instance.full_clean(exclude=list(spec.fk_by_code), validate_unique=False)
        except ValidationError as exc:
            raise RowError(self._describe(exc)) from exc
        return instance

    def _check_row(self, model, spec, key, row):
        """Raise RowError for a row that is not a table, has unknown fields or lacks its key."""
        if not isinstance(row, dict):
            raise RowError("row is not a table")
        unknown = set(row) - spec.allowed
        if unknown:
            raise RowError(f"unknown field(s): {', '.join(sorted(unknown))}")
        missing_key = [
            name
            for name in key
            if row.get(name) in EMPTY and not self._is_nullable_fk(model, spec, name)
        ]
        if missing_key:
            raise RowError(f"missing key field(s): {', '.join(missing_key)}")

    def _seed_row(self, model, spec, key, row):
        """Insert one row, or report it unchanged. Raise RowError to skip it."""
        self._check_row(model, spec, key, row)
        label = ", ".join(f"{name}={row.get(name)}" for name in key)

        # Idempotency: a row with this natural key is left exactly as it is. A
        # foreign key in the key (a user-group membership's user and group, an
        # attribute's content type) is matched by the related row's code or
        # natural key; an unknown code matches nothing and is reported by
        # _resolve_fks below.
        if model.objects.filter(**self._key_lookup(spec, key, row)).exists():
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
            # clean() normalizes the key in place (e.g. lowercases config_set)
            # even when validation fails, so a row stored under the normalized
            # key is still found and left unchanged.
            if model.objects.filter(**{name: getattr(instance, name) for name in key}).exists():
                return "unchanged", label
            raise RowError(self._describe(exc)) from exc

        instance.save()
        for name, objects in m2m_values.items():
            getattr(instance, name).set(objects)
        return "created", label

    def _is_nullable_fk(self, model, spec, name):
        """Whether ``name`` is a nullable FK, so an empty key value means NULL."""
        return name in spec.fk_by_code and model._meta.get_field(name).null

    def _key_lookup(self, spec, key, row):
        """Build the natural-key filter; an FK in the key matches by the related code."""
        lookup = {}
        for name in key:
            value = row.get(name)
            ref = spec.fk_by_code.get(name)
            if ref is None:
                lookup[name] = value
            elif value in EMPTY:
                lookup[f"{name}__isnull"] = True
            elif ref.natural_key:
                lookup[name] = self._lookup(name, ref, value)
            else:
                lookup[f"{name}__{ref.key}"] = value
        return lookup

    def _resolve_fks(self, spec, row):
        """Resolve each foreign key in the row to its related object, by code."""
        resolved = {}
        for name, ref in spec.fk_by_code.items():
            value = row.get(name)
            if value in EMPTY:
                continue  # nullable / optional reference
            resolved[name] = self._lookup(name, ref, value)
        return resolved

    def _lookup(self, name, ref, value):
        """Return the object ``ref`` names by ``value``; raise RowError if there is none."""
        model = ref.get_model()
        if ref.natural_key:
            try:
                return model._default_manager.get_by_natural_key(*str(value).split("."))
            except (model.DoesNotExist, TypeError) as exc:
                raise RowError(f"{name}: no {ref.model_label} with natural key {value!r}") from exc
        obj = model.objects.filter(**{ref.key: value}).first()
        if obj is None:
            raise RowError(f"{name}: no {ref.model_label} with {ref.key}={value!r}")
        return obj

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

    def _key_value(self, model, name, value):
        """Return ``value`` as stored in ``name``, so a TOML int matches a stored string.

        A value the field rejects is returned unchanged; it matches nothing and
        is reported where the row is built.
        """
        try:
            return self._coerce(model, name, value)
        except RowError:
            return value

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
