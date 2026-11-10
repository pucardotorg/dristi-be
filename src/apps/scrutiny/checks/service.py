"""Evaluate the advisory checks for a filing (spec 0024 #2.4)."""

import logging

from apps.core.rules.exceptions import RuleError, RuleNotFound
from apps.core.rules.services import BusinessRuleService
from apps.scrutiny import errors
from apps.scrutiny.enums import Decision

from . import contracts
from .resolver import resolve_binding

logger = logging.getLogger(__name__)


def evaluate_checks(establishment, facts):
    """Return the alerts the bound CHECKS rule gives for ``facts``.

    Evaluated on every read, because the facts depend on today. Never raises
    and never blocks the screen: a missing binding, a missing or inactive rule,
    or a result that breaks the contract is logged at error and returns the
    single ``CHECKS_UNAVAILABLE`` alert instead.
    """
    binding = resolve_binding(Decision.CHECKS, establishment)
    establishment_code = getattr(establishment, "code", None)
    if binding is None:
        return _unavailable(errors.CHECKS_NOT_BOUND, establishment_code, None, "no binding")
    try:
        contracts.validate_input(facts)
        envelope = BusinessRuleService.evaluate(binding.rule_code, facts)
        contracts.validate_output(envelope["result"])
    except RuleNotFound as exc:
        return _unavailable(errors.CHECKS_NOT_BOUND, establishment_code, binding.rule_code, exc)
    except (RuleError, contracts.ContractError) as exc:
        return _unavailable(
            errors.CHECKS_EVALUATION_FAILED, establishment_code, binding.rule_code, exc
        )
    return envelope["result"]["alerts"]


def dry_run(rule_code, payload=None):
    """Evaluate the active rule ``rule_code`` on a sample and check it keeps the contract.

    Returns the alerts. Raises ``RuleNotFound`` for a missing or inactive rule,
    another ``RuleError`` when evaluation fails, or ``ContractError``.
    """
    payload = contracts.SAMPLE_INPUT if payload is None else payload
    contracts.validate_input(payload)
    envelope = BusinessRuleService.dry_run(BusinessRuleService.get_rule(rule_code), payload)
    contracts.validate_output(envelope["result"])
    return envelope["result"]["alerts"]


def _unavailable(error, establishment_code, rule_code, reason):
    logger.error(
        "event=SCRUTINY_CHECKS_UNAVAILABLE code=%s establishment=%s rule=%s reason=%s",
        error.code,
        establishment_code,
        rule_code,
        reason,
    )
    return [dict(contracts.CHECKS_UNAVAILABLE)]
