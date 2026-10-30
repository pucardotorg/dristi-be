"""Registry of seedable models for the ``seed`` management command (spec 0025).

A :class:`SeedSpec` is a pure-data description of how one model is seeded from a
TOML file: its natural key, the scalar fields a row may set, and the foreign-key
and many-to-many fields resolved by a related row's natural key (its code). The
``seed`` command owns all the procedural work; specs carry no logic.
"""

from dataclasses import dataclass, field

from django.apps import apps
from django.db.models import Model


@dataclass(frozen=True)
class FkRef:
    """A related model matched by one of its fields (its natural key)."""

    model_label: str
    key: str = "code"

    def get_model(self) -> type[Model]:
        """Return the related model class."""
        return apps.get_model(self.model_label)


@dataclass(frozen=True)
class SeedSpec:
    """How to seed one model from a TOML file."""

    model_label: str
    key: tuple[str, ...]
    fields: tuple[str, ...]
    fk_by_code: dict[str, FkRef] = field(default_factory=dict)
    m2m_by_code: dict[str, FkRef] = field(default_factory=dict)
    # Relative load order across files (low first), so referents load first.
    order: int = 0

    def get_model(self) -> type[Model]:
        """Return the target model class."""
        return apps.get_model(self.model_label)

    @property
    def allowed(self) -> set[str]:
        """Every row key this spec accepts (scalar, FK and M2M fields)."""
        return set(self.fields) | set(self.fk_by_code) | set(self.m2m_by_code)


_REGISTRY: dict[str, SeedSpec] = {}


def register(spec: SeedSpec) -> None:
    """Register ``spec`` under its model label (case-insensitive)."""
    _REGISTRY[spec.model_label.lower()] = spec


def lookup(model_label: str) -> SeedSpec | None:
    """Return the spec for ``model_label``, or ``None`` if not registered."""
    return _REGISTRY.get(model_label.lower())


def all_specs() -> list[SeedSpec]:
    """Return every registered spec in load order, then by model label."""
    return sorted(_REGISTRY.values(), key=lambda spec: (spec.order, spec.model_label))
