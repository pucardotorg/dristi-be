"""Engine-agnostic contract for compiling and evaluating a rule expression."""

import abc
import copy
import ctypes
import threading
import time
from collections import OrderedDict
from typing import Any

from django.conf import settings

from ..exceptions import RuleError, RuleEvaluationError

# Upper bound on memoized compiled artefacts per adapter.
MEMO_MAX_ENTRIES = 256


class _EvaluationInterrupted(BaseException):
    """Raised asynchronously inside a guard thread that exceeded its timeout.

    A ``BaseException`` so that a library's ``except Exception`` cannot
    swallow it.
    """


def _interrupt(thread):
    """Ask ``thread`` to raise ``_EvaluationInterrupted`` at its next bytecode.

    This stops pure-Python work (rule-engine). Code running inside a native
    extension only sees it once control returns to Python (spec 0019 #11.5).
    """
    ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread.ident), ctypes.py_object(_EvaluationInterrupted)
    )


class RuleEngine(abc.ABC):
    """Engine-agnostic contract for compiling and evaluating a rule expression.

    ``cache_key`` is an optional, opaque ``(rule.id, rule.updated_at)`` tuple
    under which an adapter may memoize its compiled artefact (spec 0019 #7).
    Callers evaluating an unsaved rule (the admin dry run) pass ``None``.
    """

    engine: str  # BusinessRule.RuleEngineType value

    def __init__(self):
        self._memo = OrderedDict()
        self._memo_lock = threading.Lock()

    @abc.abstractmethod
    def validate(self, rule_expression: str, rule_input_schema: dict) -> None:
        """Raise RuleDefinitionError if the expression cannot be compiled, or is
        not type-compatible with the declared input schema."""

    @abc.abstractmethod
    def referenced_inputs(self, rule_expression: str, rule_input_schema: dict) -> set[str]:
        """Return the input identifiers the expression reads (spec 0019 #2.6)."""

    @abc.abstractmethod
    def evaluate(
        self, rule_expression: str, payload: dict, rule_input_schema: dict, *, cache_key=None
    ) -> Any:
        """Return the raw engine output for the expression applied to payload."""

    def trace(self, rule_expression: str, payload: dict, rule_input_schema: dict) -> Any:
        """Return engine-native trace data for one evaluation, or ``None``.

        Only the admin dry run calls this; evaluation proper never traces.
        """
        return None

    def evaluate_with_timeout(
        self, rule_expression: str, payload: dict, rule_input_schema: dict, *, cache_key=None
    ) -> Any:
        """Deep-copy the payload, apply the timeout, and translate engine errors."""
        payload = copy.deepcopy(payload)
        return self._guarded(
            lambda: self.evaluate(rule_expression, payload, rule_input_schema, cache_key=cache_key)
        )

    def trace_with_timeout(self, rule_expression: str, payload: dict, rule_input_schema: dict):
        """:meth:`trace` under the same guard as :meth:`evaluate_with_timeout`."""
        payload = copy.deepcopy(payload)
        return self._guarded(lambda: self.trace(rule_expression, payload, rule_input_schema))

    def _guarded(self, call):
        """Run ``call`` in a guard thread bounded by RULES_EVALUATION_TIMEOUT_SECONDS.

        Module exceptions raised by ``call`` propagate unchanged, so a compile
        failure stays a RuleDefinitionError. Anything else becomes a
        RuleEvaluationError.
        """
        timeout = settings.RULES_EVALUATION_TIMEOUT_SECONDS
        outcome = {}

        def target():
            try:
                outcome["value"] = call()
            except _EvaluationInterrupted:
                pass
            except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
                outcome["error"] = exc

        thread = threading.Thread(target=target, name=f"rule-eval-{self.engine}", daemon=True)
        started = time.monotonic()
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            _interrupt(thread)
            raise RuleEvaluationError(f"Evaluation exceeded the {timeout}s timeout.")
        # A long call inside a C extension (a backtracking regex, a huge
        # $range) holds the GIL, so join() only returns once it has finished.
        # The caller still waited, but a late result must not count as success.
        elapsed = time.monotonic() - started
        if elapsed > timeout:
            raise RuleEvaluationError(
                f"Evaluation exceeded the {timeout}s timeout (took {elapsed:.2f}s)."
            )
        if "error" in outcome:
            exc = outcome["error"]
            if isinstance(exc, RuleError):
                raise exc
            raise RuleEvaluationError(f"Evaluation failed: {exc}") from exc
        return outcome["value"]

    def _memoized(self, cache_key, factory):
        """Return ``factory()``, memoized under ``cache_key`` when one is given."""
        if cache_key is None:
            return factory()
        with self._memo_lock:
            if cache_key in self._memo:
                self._memo.move_to_end(cache_key)
                return self._memo[cache_key]
        value = factory()
        with self._memo_lock:
            self._memo[cache_key] = value
            while len(self._memo) > MEMO_MAX_ENTRIES:
                self._memo.popitem(last=False)
        return value
