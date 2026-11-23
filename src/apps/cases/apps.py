"""Cases app configuration."""

from django.apps import AppConfig


class CasesConfig(AppConfig):
    """Cases app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cases"
    verbose_name = "Cases"

    def ready(self):
        """Register the settings checks and the e-sign authorizer for case filings."""
        from apps.esign.constants import EntityType
        from apps.esign.permissions import register_entity_authorizer

        from .services import checks  # noqa: F401
        from .services.signing import can_sign_case_filing

        register_entity_authorizer(EntityType.CASE_FILING.value, can_sign_case_filing)
