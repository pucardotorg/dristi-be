"""File storage models."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.core.models import BaseActivatableModel, BaseModel


class FileType(models.TextChoices):
    """Controlled type of a stored file.

    The type describes the role a file plays for the consuming module, not its
    media type. Typical formats per value:

    ``PDF``
        PDF.
    ``DOCUMENT``
        PDF, DOC, DOCX, ODT.
    ``IMAGE``
        JPG, JPEG, PNG, etc.
    ``SIGNATURE``
        PNG, JPEG.
    ``DIGITALLY_SIGNED``
        PDF, XML, etc.
    """

    PDF = "pdf", "PDF"
    DOCUMENT = "document", "Document"
    IMAGE = "image", "Image"
    SIGNATURE = "signature", "Signature"
    DIGITALLY_SIGNED = "digitally_signed", "Digitally signed"


class FileTag(BaseModel):
    """Reusable tag that can be associated with many files.

    Tags are global across the system and stored as slugs, so that caller
    supplied names such as "identity", "Identity", "IDENTITY" and
    "Address Proof" resolve to a single canonical row.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("name",)

    def clean(self):
        """Slugify the tag name so equivalent inputs collapse to one row.

        Non-ASCII names are rejected rather than slugified: slugify would drop
        or transliterate the characters, silently storing a tag the caller
        never asked for.
        """
        super().clean()
        name = (self.name or "").strip()
        if not name.isascii():
            raise ValidationError({"name": "name must contain only ASCII characters."})
        self.name = slugify(name)
        if not self.name:
            raise ValidationError(
                {"name": "name must contain at least one alphanumeric character."}
            )

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class File(BaseModel, BaseActivatableModel):
    """Metadata for a single file whose content lives in Object Storage.

    The database holds only metadata and the Object Storage key; the key is
    internal to this module and is not exposed to consuming services.

    Every file records the user that uploaded it. Uploads made by a
    system/backend process are attributed to a dedicated service-account user
    rather than being left unattributed.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="files",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="uploaded_files",
    )
    file_type = models.CharField(max_length=50, choices=FileType.choices, db_index=True)
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    storage_path = models.CharField(max_length=1024, unique=True)
    tags = models.ManyToManyField(FileTag, related_name="files", blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        indexes = [
            models.Index(fields=["organization", "file_type"]),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.id})"
