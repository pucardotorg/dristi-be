"""Cache invalidation for template configuration (spec 0016 #9)."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import PDFTemplate, PDFTemplateVersion
from .services.config_loader import PDFConfigLoader


@receiver([post_save, post_delete], sender=PDFTemplate)
def invalidate_template(sender, instance, **kwargs):
    """A template was (de)activated or renamed: drop its active-version lookup."""
    PDFConfigLoader.invalidate_key(instance.key)


@receiver([post_save, post_delete], sender=PDFTemplateVersion)
def invalidate_template_version(sender, instance, **kwargs):
    """A version changed: drop the key lookup and the version's own entry."""
    PDFConfigLoader.invalidate_key(instance.template.key)
    PDFConfigLoader.invalidate_version(instance.pk)
