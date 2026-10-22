"""Request context propagated through generation (spec 0016 #13).

The context travels from the API into the job row and from there to the
worker, and is forwarded to external API calls, localization lookups and log
lines. It never carries credentials: authorization headers are not captured,
and the worker re-acquires service credentials from configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DEFAULT_LOCALE = "en_IN"


@dataclass(frozen=True)
class RequestContext:
    """Who asked for a document, for which tenant/entity, in which locale."""

    tenant_id: str
    key: str = ""
    entity_id: str = ""
    locale: str = DEFAULT_LOCALE
    correlation_id: str = ""
    user_id: str = ""
    job_id: str = ""

    def as_dict(self) -> dict:
        """Return the context as the ``meta`` variable seen by mappings and templates."""
        return asdict(self)

    @classmethod
    def for_job(cls, job) -> RequestContext:
        """Rebuild the context a job was created with."""
        return cls(
            tenant_id=job.tenant_id,
            key=job.key,
            entity_id=job.entity_id,
            locale=job.locale or DEFAULT_LOCALE,
            correlation_id=job.correlation_id,
            user_id=str(job.requested_by_id or ""),
            job_id=str(job.id),
        )
