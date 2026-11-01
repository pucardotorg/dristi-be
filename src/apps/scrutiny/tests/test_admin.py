"""Admin pages of the scrutiny models (spec 0024 #10)."""

from django.contrib.admin.sites import AdminSite

from apps.scrutiny.admin import ScrutinyFlagInline, ScrutinyFlagResponseInline
from apps.scrutiny.models import ScrutinyFlag, ScrutinyRound


def test_inlines_add_nothing():
    site = AdminSite()
    assert ScrutinyFlagInline(ScrutinyRound, site).has_add_permission(None) is False
    assert ScrutinyFlagResponseInline(ScrutinyFlag, site).has_add_permission(None) is False
