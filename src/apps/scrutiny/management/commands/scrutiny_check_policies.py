"""Report organizations without a checks rule and bindings that cannot run (spec 0024 #2.4)."""

from django.core.management.base import BaseCommand, CommandError

from apps.core.rules.exceptions import RuleError, RuleNotFound
from apps.organizations.models import Organization
from apps.scrutiny.checks import service
from apps.scrutiny.checks.contracts import ContractError
from apps.scrutiny.checks.resolver import resolve_binding
from apps.scrutiny.enums import Decision
from apps.scrutiny.models import ScrutinyRuleBinding


class Command(BaseCommand):
    help = (
        "Report active organizations that no CHECKS binding reaches, active bindings "
        "to a missing or inactive rule, and bindings whose rule fails the dry run. "
        "Exits non-zero when anything is reported."
    )

    def handle(self, *args, **options):
        problems = []

        for organization in Organization.objects.active().order_by("code"):
            if resolve_binding(Decision.CHECKS, organization) is None:
                problems.append(f"UNBOUND {organization.code}: no {Decision.CHECKS} binding")

        bindings = ScrutinyRuleBinding.objects.active().select_related("organization")
        for binding in bindings.order_by("decision", "rule_code"):
            label = f"{binding.decision} @ {binding.organization or 'national default'}"
            try:
                service.dry_run(binding.rule_code)
            except RuleNotFound:
                problems.append(
                    f"INACTIVE_RULE {label}: {binding.rule_code} is missing or inactive"
                )
            except (RuleError, ContractError) as exc:
                problems.append(f"DRY_RUN_FAILED {label}: {binding.rule_code}: {exc}")

        for problem in problems:
            self.stdout.write(problem)
        if problems:
            raise CommandError(f"{len(problems)} scrutiny check policy problem(s).")
        self.stdout.write(
            self.style.SUCCESS("Every organization resolves to a working checks rule.")
        )
