"""Address models (spec 0020 §7)."""

import hashlib
import unicodedata
import uuid

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

PINCODE_REGEX = r"^[1-9][0-9]{5}$"

# Fields that describe the address itself: hashed for deduplication and
# copied into a revision. ``created_by`` is deliberately not one of them.
CONTENT_FIELDS = ("line1", "city", "state", "pincode", "district", "police_station")


class AddressImmutableError(Exception):
    """Raised when an existing address is modified or deleted in place."""


# Invisible characters that carry no meaning in an address, often pasted in by
# accident. The zero-width joiner and non-joiner (U+200D, U+200C) are kept:
# Malayalam and Devanagari use them to choose how letters join.
_INVISIBLE = dict.fromkeys(map(ord, "​⁠﻿"))


def normalize_field(field, value):
    """Return ``value`` in the canonical form stored for ``field``.

    The text is put in Unicode NFC form, so the same visible Malayalam or Hindi
    text typed with different input methods is stored, and hashed, the same way,
    and invisible characters such as a zero-width space are removed.
    Surrounding whitespace is dropped and inner runs collapse to one space, so
    "12  MG Road " and "12 MG Road" are the same address. A pincode keeps no
    spaces at all, so "560 001" becomes "560001". Case is kept as entered.
    """
    if value is None:
        return value
    text = unicodedata.normalize("NFC", str(value)).translate(_INVISIBLE)
    parts = text.split()
    return "".join(parts) if field == "pincode" else " ".join(parts)


def address_hash(values):
    """Return the SHA-256 hex digest of the canonical form of ``values``.

    Only whitespace is normalized; case is significant, so "MG Road" and
    "mg road" are different addresses. Otherwise whoever typed an address
    first would fix its casing for everyone, and a case-only correction could
    never be saved. Fields are joined with a unit separator, which cannot
    appear in a normalized value, so ("a b", "c") and ("a", "b c") never collide.
    """
    canonical = "\x1f".join(normalize_field(field, values[field]) for field in CONTENT_FIELDS)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AddressManager(models.Manager):
    """Manager whose entry point reuses an identical address instead of copying it."""

    def get_or_create_address(self, created_by=None, **fields):
        """Return ``(address, created)`` for ``fields``, reusing an identical row.

        Values are normalized and validated first. When an address with the
        same canonical form exists it is returned as is, keeping its original
        ``created_by``; otherwise a new row is inserted. Safe under concurrent
        callers: the unique ``hash`` index makes the losing insert fall back to
        the existing row.
        """
        unknown = set(fields) - set(CONTENT_FIELDS)
        if unknown:
            raise ValueError(f"Not address fields: {sorted(unknown)}")

        values = {field: normalize_field(field, fields.get(field, "")) for field in CONTENT_FIELDS}
        candidate = self.model(created_by=created_by, **values)
        candidate.full_clean(exclude=["hash"], validate_unique=False)

        return self.get_or_create(
            hash=address_hash(values),
            defaults={**values, "created_by": created_by},
        )

    def bulk_create(self, objs, *args, **kwargs):
        """Normalize and hash each address, which ``bulk_create`` would skip.

        Django's ``bulk_create`` does not call ``save()``, so without this the
        rows would be stored with an empty ``hash`` and never deduplicate.
        """
        objs = list(objs)
        for address in objs:
            address._normalize()
            address.hash = address_hash(address._content())
        return super().bulk_create(objs, *args, **kwargs)


class Address(models.Model):
    """An Indian postal address associated with a person or organization.

    Addresses are immutable. Court records require stable addresses: if a
    notice was served to an address in January, the case file must forever
    show that address, even if the person has since moved. Editing an address
    therefore creates a new row (see :meth:`revise`) and the caller repoints
    its foreign key; the old row is never rewritten or deleted.

    Identical addresses share one row: create them through
    ``Address.objects.get_or_create_address`` rather than ``create``.
    """

    CONTENT_FIELDS = CONTENT_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line1 = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(
        max_length=6,
        db_index=True,
        validators=[
            RegexValidator(PINCODE_REGEX, "Enter a valid 6-digit pincode not starting with 0.")
        ],
    )
    district = models.CharField(max_length=100)
    police_station = models.CharField(max_length=255)
    # SHA-256 of the canonical content; the unique index is what deduplicates.
    hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # PROTECT, not SET_NULL: nulling the creator would rewrite an immutable row.
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="addresses_created",
    )

    objects = AddressManager()

    class Meta:
        """Meta options."""

        # Newest first, as for BaseModel subclasses.
        ordering = ("-created_at",)
        constraints = [
            # A 6-digit pincode not starting with 0.
            models.CheckConstraint(
                check=Q(pincode__regex=PINCODE_REGEX),
                name="address_pincode_valid",
            ),
            # A row written without its hash (raw SQL, a bypassed save) is
            # refused rather than stored undeduplicatable.
            models.CheckConstraint(
                check=Q(hash__regex=r"^[0-9a-f]{64}$"),
                name="address_hash_is_sha256",
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.line1}, {self.city}, {self.district}, {self.state} - {self.pincode}"

    def save(self, *args, **kwargs):
        """Insert a new address; refuse to update an existing one.

        The stored values are normalized and ``hash`` is always recomputed
        from them, so a caller can never insert a hash that does not match.
        """
        if not self._state.adding:
            raise AddressImmutableError(
                f"Address {self.pk} is immutable; use revise() to create a new one."
            )
        self._normalize()
        self.hash = address_hash(self._content())
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse to delete an address."""
        raise AddressImmutableError(f"Address {self.pk} is immutable and cannot be deleted.")

    def clean_fields(self, exclude=None):
        """Validate the values as they will be stored.

        Normalizing first means a whitespace-only value is checked as the empty
        string it would be saved as, so "required" rejects it.
        """
        self._normalize()
        super().clean_fields(exclude=exclude)

    def validate_constraints(self, exclude=None):
        """Leave the hash check to the database.

        ``hash`` is derived, and ``save()`` always computes it, so an unsaved
        address has none yet; checking it here would reject every new address.
        """
        super().validate_constraints(exclude={*(exclude or ()), "hash"})

    def validate_unique(self, exclude=None):
        """Also reject a new address identical to an existing one.

        ``hash`` is not a form field, so Django's own unique check skips it;
        without this the admin would hit the unique index and return a 500.

        The hash needs every content field, so the check is skipped while any
        is missing or excluded: ``full_clean`` excludes fields that already
        failed, and reports those errors instead.
        """
        super().validate_unique(exclude=exclude)
        if not self._state.adding or set(CONTENT_FIELDS) & set(exclude or ()):
            return
        self._normalize()
        if any(value in (None, "") for value in self._content().values()):
            return
        if Address.objects.filter(hash=address_hash(self._content())).exists():
            raise ValidationError({NON_FIELD_ERRORS: ["This address already exists."]})

    def revise(self, created_by=None, **changes):
        """Return the address holding this one's values plus ``changes``.

        This address is left untouched. The result is an existing identical
        address when there is one (``self`` if nothing changed), otherwise a
        new row. The caller must repoint its foreign key at the returned row.
        """
        unknown = set(changes) - set(CONTENT_FIELDS)
        if unknown:
            raise ValueError(f"Cannot revise non-content fields: {sorted(unknown)}")

        values = {**self._content(), **changes}
        address, _ = Address.objects.get_or_create_address(created_by=created_by, **values)
        return address

    def _content(self):
        """Return this address's content fields as a dict."""
        return {field: getattr(self, field) for field in CONTENT_FIELDS}

    def _normalize(self):
        """Rewrite the content fields into their canonical stored form."""
        for field in CONTENT_FIELDS:
            setattr(self, field, normalize_field(field, getattr(self, field)))
