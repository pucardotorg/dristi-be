"""Engine registry: ``BusinessRule.engine`` value -> adapter instance (spec 0019 #4.2).

Built once per process by :meth:`apps.core.apps.CoreConfig.ready`, so a missing
or broken engine dependency fails at startup rather than at first evaluation.
"""

from ..exceptions import EngineNotAvailable
from .base import RuleEngine

_REGISTRY: dict[str, RuleEngine] = {}


def build_registry():
    """Instantiate and register both adapters. Performs no database access."""
    from .expression import RuleEngineAdapter
    from .gorules import GoRulesRuleEngine

    _REGISTRY.clear()
    for adapter in (RuleEngineAdapter(), GoRulesRuleEngine()):
        _REGISTRY[adapter.engine] = adapter


def get_engine(engine) -> RuleEngine:
    """Return the adapter for ``engine`` or raise EngineNotAvailable."""
    try:
        return _REGISTRY[engine]
    except KeyError:
        raise EngineNotAvailable(f"No rule engine adapter is registered for {engine!r}.") from None
