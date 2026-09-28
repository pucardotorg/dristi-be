"""Adapter over ``apps.files.services`` (spec 0015 #4.2, spec 0014 #2).

The domain never sees the storage module's batch envelope, its models or its
exceptions: it asks for bytes by ``file_id`` and gets a ``file_id`` back when it
stores something new. Document bytes are never logged here.
"""

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from ..constants import PDF_CONTENT_TYPE
from ..exceptions import ESignFileStorageError, ESignSourceNotFound

FILE_SERVICE_MODULE = "apps.files.services"

# 0014 #6 leaves the not-found error as either ``File.DoesNotExist`` or a
# module-level ``FileNotFound``, so both names are recognised.
NOT_FOUND_ERROR_NAMES = frozenset({"DoesNotExist", "FileNotFound", "FileNotFoundError"})


class FileClient:
    """In-process client for the File Storage Service."""

    def get_metadata(self, file_id: str) -> dict:
        """Return the stored metadata for ``file_id``."""

        services = self._service_module()
        try:
            metadata = services.get_file(str(file_id))
        except Exception as exc:
            raise self._translate(exc) from exc
        if not isinstance(metadata, dict):
            metadata = self._as_metadata_dict(metadata)
        return metadata

    def get_content(self, file_id: str) -> bytes:
        """Return the bytes of ``file_id``, honouring the configured read limit."""

        services = self._service_module()
        try:
            stream = services.get_file_content(str(file_id))
        except Exception as exc:
            raise self._translate(exc) from exc

        limit = int(getattr(settings, "PDF_MAX_SIGN_INPUT_BYTES", 0) or 0)
        try:
            content = stream.read(limit + 1) if limit else stream.read()
        except Exception as exc:
            raise ESignFileStorageError("The document could not be read.") from exc
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

        if isinstance(content, str):
            content = content.encode()
        if not content:
            raise ESignFileStorageError("The stored document is empty.")
        if limit and len(content) > limit:
            raise ESignFileStorageError("The stored document is too large to sign.")
        return bytes(content)

    def upload(
        self,
        content: bytes,
        *,
        filename: str,
        file_type: str,
        user_id: str,
        organization_id: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Store ``content`` and return its ``file_id``."""

        services = self._service_module()
        upload = SimpleUploadedFile(filename, content, content_type=PDF_CONTENT_TYPE)
        payload = {
            "organization_id": str(organization_id) if organization_id else None,
            "user_id": str(user_id),
            "files": [
                {
                    "file": upload,
                    "file_type": file_type,
                    "tags": list(tags or []),
                }
            ],
        }
        try:
            result = services.upload_file(payload)
        except Exception as exc:
            raise self._translate(exc, default=ESignFileStorageError) from exc

        return self._single_file_id(result)

    def delete(self, file_id: str) -> None:
        """Delete ``file_id``; used for placeholder cleanup only."""

        services = self._service_module()
        try:
            services.delete_file(str(file_id))
        except Exception as exc:
            raise self._translate(exc) from exc

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _service_module():
        """Import the File Storage service module, or fail with a safe error."""

        try:
            from importlib import import_module

            return import_module(FILE_SERVICE_MODULE)
        except ImportError as exc:
            raise ESignFileStorageError("The file storage service is not available.") from exc

    @staticmethod
    def _as_metadata_dict(metadata) -> dict:
        """Accept a ``File`` instance as well as the documented dict shape."""

        return {
            "id": str(getattr(metadata, "id", "")),
            "content_type": getattr(metadata, "content_type", ""),
            "file_name": getattr(metadata, "file_name", ""),
            "file_size": getattr(metadata, "file_size", None),
            "file_type": getattr(metadata, "file_type", ""),
            "organization_id": getattr(metadata, "organization_id", None),
            "user_id": getattr(metadata, "user_id", None),
        }

    @staticmethod
    def _single_file_id(result) -> str:
        """Unwrap the single-file batch response of 0014 #3."""

        files = result.get("files") if isinstance(result, dict) else None
        if not files:
            raise ESignFileStorageError("The file storage service returned no file id.")
        entry = files[0]
        file_id = entry.get("id") if isinstance(entry, dict) else getattr(entry, "id", None)
        if not file_id:
            raise ESignFileStorageError("The file storage service returned no file id.")
        return str(file_id)

    @staticmethod
    def _translate(exc: Exception, default=None) -> Exception:
        """Map a storage exception onto this module's failure codes."""

        from ..exceptions import ESignError

        if isinstance(exc, ESignError):
            return exc
        if type(exc).__name__ in NOT_FOUND_ERROR_NAMES:
            return ESignSourceNotFound()
        return (default or ESignFileStorageError)()
