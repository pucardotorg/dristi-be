"""Charge lines → e-GRAS scheme (head of account) pairs (spec 0022 #4.3).

e-GRAS is paid *per government scheme*, not per line item. There is no default
scheme — crediting money to the wrong head of account is worse than refusing
the payment — and the addon never rounds: e-GRAS carries whole rupees while
0017 carries fractional fees, so a head whose lines do not sum to a whole rupee
is a fee-master decision, not a transport one.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from apps.payments.providers.base import ChargeLine, ProviderPermanentError

from . import constants


@dataclass(frozen=True)
class Scheme:
    """One head of account and the whole-rupee amount collected into it."""

    code: str
    amount: int


def resolve_scheme(line: ChargeLine, scheme_map: Mapping[str, str]) -> str:
    """Return the 17-character scheme code a charge line credits (spec 0022 #4.3).

    ``account_head`` is tried first because it is the fee master's own snapshot,
    then ``account_head`` taken as a literal scheme code, then ``charge_type``.
    An unmapped charge is a permanent, operator-visible configuration error.
    """

    if line.account_head and line.account_head in scheme_map:
        return scheme_map[line.account_head]
    if line.account_head and constants.SCHEME_CODE_RE.match(line.account_head):
        return line.account_head
    if line.charge_type and line.charge_type in scheme_map:
        return scheme_map[line.charge_type]
    raise ProviderPermanentError(
        constants.EGRAS_SCHEME_UNMAPPED,
        f"No e-GRAS scheme is configured for charge {line.charge_type!r} "
        f"(account head {line.account_head!r}).",
    )


def build_schemes(
    lines: Iterable[ChargeLine],
    *,
    scheme_map: Mapping[str, str],
    max_schemes: int,
) -> list[Scheme]:
    """Group charge lines by scheme and return them in deterministic order.

    Each scheme's amount must be a whole number of rupees, and the number of
    schemes must not exceed ``max_schemes``. Ordering by scheme code keeps the
    built request identical on replay (spec 0017 #9.2 rule 2).
    """

    totals: dict[str, Decimal] = {}
    for line in lines:
        code = resolve_scheme(line, scheme_map)
        totals[code] = totals.get(code, Decimal(0)) + line.amount

    schemes = []
    for code in sorted(totals):
        amount = totals[code]
        if amount != amount.to_integral_value():
            raise ProviderPermanentError(
                constants.EGRAS_FRACTIONAL_AMOUNT,
                f"Scheme {code} sums to {amount}, which is not a whole number of rupees.",
            )
        schemes.append(Scheme(code=code, amount=int(amount)))

    if len(schemes) > max_schemes:
        raise ProviderPermanentError(
            constants.EGRAS_TOO_MANY_SCHEMES,
            f"{len(schemes)} schemes exceed the e-GRAS limit of {max_schemes}.",
        )

    return schemes
