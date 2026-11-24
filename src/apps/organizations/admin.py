"""Organizations admin registration, and court roles and assignments (spec 0029 #9.1)."""

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin
from apps.locations.models import LEAF_TYPES, Location

from . import court_actions, selectors, services
from .enums import CourtLevel
from .models import (
    CourtRole,
    CourtRoleAction,
    CourtroomAssignment,
    Organization,
    RoleAssignment,
)


class OrganizationAdminForm(forms.ModelForm):
    """Admin form enforcing the jurisdiction requirement for active organizations."""

    class Meta:
        """Meta options."""

        model = Organization
        fields = "__all__"

    def clean(self):
        """Require at least one jurisdiction location for active organizations."""
        cleaned_data = super().clean()
        if cleaned_data.get("is_active") and not cleaned_data.get("jurisdictions"):
            raise forms.ValidationError(
                "Active organizations must have at least one jurisdiction location."
            )
        return cleaned_data


class ReadOnlyInline(admin.TabularInline):
    """A list of related rows, managed on their own admin pages (through the services)."""

    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        """Rows are added on their own admin page."""
        return False

    def has_change_permission(self, request, obj=None):
        """Rows are changed on their own admin page."""
        return False


class OrganizationStaffInline(ReadOnlyInline):
    """Who has this courtroom on their list."""

    model = CourtroomAssignment
    fk_name = "courtroom"
    fields = ("user", "is_active", "updated_at")
    readonly_fields = fields
    verbose_name = "staff member (courtroom list)"
    verbose_name_plural = "Staff (courtroom list)"


class OrganizationRoleInline(ReadOnlyInline):
    """Who holds which role here."""

    model = RoleAssignment
    fk_name = "organization"
    fields = ("user", "role", "is_active", "updated_at")
    readonly_fields = fields
    verbose_name = "role assignment"
    verbose_name_plural = "Role assignments"


@admin.register(Organization)
class OrganizationAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for organizations."""

    form = OrganizationAdminForm
    list_display = (
        "code",
        "name",
        "short_name",
        "organization_type",
        "court_level",
        "parent",
        "is_active",
    )
    list_filter = ("organization_type", "court_level", "is_active")
    search_fields = ("code", "name", "short_name")
    readonly_fields = ("id", "created_at", "updated_at")
    filter_horizontal = ("jurisdictions",)
    inlines = (OrganizationStaffInline, OrganizationRoleInline)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Offer administrative areas only as jurisdictions, never the many pincodes or banks."""
        if db_field.name == "jurisdictions":
            kwargs["queryset"] = Location.objects.exclude(location_type__in=LEAF_TYPES)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


# ---------------------------------------------------------------------------
# Court roles
# ---------------------------------------------------------------------------


def action_choices():
    """Registered actions grouped by their PRD role, for a select."""
    groups = {}
    for action in court_actions.all():
        label = f"{action.code}: {action.label} ({action.level.lower()}"
        label += ", scoped)" if action.scoped else ")"
        groups.setdefault(action.group, []).append((action.code, label))
    return [("", "---------"), *groups.items()]


def group_choices():
    """The PRD roles the registered actions belong to."""
    return [(group, group) for group in sorted({a.group for a in court_actions.all()})]


class CourtRoleActionForm(forms.ModelForm):
    """One action of a role, picked from the registry; a scope only on a scoped action."""

    action = forms.ChoiceField()
    scope = forms.JSONField(
        required=False,
        help_text=(
            'Scoped actions only. Empty covers everything; e.g. {"process_types": ["SUMMONS"], '
            '"channels": ["RPAD"]}. A missing key covers every code on that axis.'
        ),
    )

    class Meta:
        """Meta options."""

        model = CourtRoleAction
        fields = ("action", "scope")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = action_choices()
        current = self.initial.get("action")
        if current and not court_actions.is_registered(current):
            # Removed without a data migration (W004): keep it visible so it can be deleted.
            choices.append(("Not declared", [(current, f"{current} (not declared; ignored)")]))
        self.fields["action"].choices = choices

    def _post_clean(self):
        """Skip per-row model validation: the formset validates the whole set at once."""


class CourtRoleActionFormSet(BaseInlineFormSet):
    """Validates the role's whole action list through the services, before anything is saved."""

    def entries(self):
        """The ``(code, scope)`` rows kept in the form, plus whole groups ticked on the role."""
        entries = []
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE") or not form.cleaned_data.get("action"):
                continue
            entries.append((form.cleaned_data["action"], form.cleaned_data.get("scope")))
        held = {code for code, _ in entries}
        for group in self.data.getlist("add_groups") if hasattr(self.data, "getlist") else []:
            for action in court_actions.all():
                if action.group == group and action.code not in held:
                    entries.append((action.code, None))
                    held.add(action.code)
        return entries

    def clean(self):
        """Refuse an invalid set (#5.2, #5.4) with the services' own messages."""
        super().clean()
        if any(self.errors):
            return
        try:
            self.cleaned_entries = services.clean_role_actions(self.instance, self.entries())
        except ValidationError as exc:
            raise ValidationError(exc.messages) from exc


class CourtRoleActionInline(admin.TabularInline):
    """The actions a role holds; saved through ``services.set_role_actions``."""

    model = CourtRoleAction
    form = CourtRoleActionForm
    formset = CourtRoleActionFormSet
    extra = 1
    fields = ("action", "scope")


class CourtRoleForm(forms.ModelForm):
    """A role, with a shortcut to add every action of a PRD role at once."""

    add_groups = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Add whole PRD roles",
        help_text="Adds every action of each ticked PRD role, on top of the rows below.",
    )

    class Meta:
        """Meta options."""

        model = CourtRole
        fields = ("code", "name", "establishment", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["add_groups"].choices = group_choices()
        if "establishment" in self.fields:
            self.fields["establishment"].queryset = Organization.objects.filter(
                court_level=CourtLevel.ESTABLISHMENT
            )

    def _post_clean(self):
        """After the model's own validation, refuse moving a role away from its assignments."""
        super()._post_clean()
        if not self.errors:
            try:
                services.validate_role_fields(self.instance)
            except ValidationError as exc:
                self.add_error(None, exc)


@admin.register(CourtRole)
class CourtRoleAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Court roles: staff titles built from actions. Deactivate instead of deleting."""

    form = CourtRoleForm
    inlines = (CourtRoleActionInline,)
    list_display = ("code", "name", "establishment", "action_count", "holder_count", "is_active")
    list_filter = ("is_active", "establishment")
    search_fields = ("code", "name")
    readonly_fields = ("applies_to",)
    fields = ("code", "name", "establishment", "is_active", "applies_to", "add_groups")

    def get_queryset(self, request):
        """Load the establishment for the list."""
        return super().get_queryset(request).select_related("establishment")

    @admin.display(description="actions")
    def action_count(self, obj):
        """How many action rows the role holds."""
        return obj.actions.count()

    @admin.display(description="active holders")
    def holder_count(self, obj):
        """How many active assignments the role has."""
        return obj.assignments.filter(is_active=True).count()

    @admin.display(description="A change applies to")
    def applies_to(self, obj):
        """How many users and organizations a change to this role applies to (#9.1)."""
        if obj is None or obj.pk is None:
            return "Nobody yet."
        assignments = obj.assignments.filter(is_active=True, user__is_active=True)
        users = assignments.values("user_id").distinct().count()
        organizations = assignments.values("organization_id").distinct().count()
        return f"{users} user(s) at {organizations} organization(s)."

    def save_model(self, request, obj, form, change):
        """Save the role's own fields through the services."""
        services.save_role(obj, actor=request.user)

    def save_related(self, request, form, formsets, change):
        """Save the actions through ``set_role_actions`` instead of the inline formset."""
        form.save_m2m()
        for formset in formsets:
            if isinstance(formset, CourtRoleActionFormSet):
                services.set_role_actions(
                    form.instance, formset.cleaned_entries, actor=request.user
                )
                # The change message reads these; history records the rows themselves.
                formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []

    def has_delete_permission(self, request, obj=None):
        """Roles are deactivated, never deleted."""
        return False


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


class AssignmentAdminMixin:
    """Shared behaviour: save through the services, never delete."""

    list_select_related = True

    def has_delete_permission(self, request, obj=None):
        """Assignments are deactivated, never deleted."""
        return False

    def get_readonly_fields(self, request, obj=None):
        """Who and where are fixed once created: deactivate and add a new one instead."""
        readonly = tuple(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly += self.identity_fields
        return readonly

    def get_fields(self, request, obj=None):
        """A new assignment is always active; the flag is edited on an existing one."""
        fields = tuple(super().get_fields(request, obj))
        if obj is None:
            fields = tuple(f for f in fields if f not in ("is_active", *self.readonly_fields))
        return fields

    @staticmethod
    def _adopt(obj, saved):
        """Point the admin's object at the row the service saved (it may reactivate an old one)."""
        obj.pk = saved.pk
        obj._state.adding = False


@admin.register(CourtroomAssignment)
class CourtroomAssignmentAdmin(AssignmentAdminMixin, SimpleHistoryAdmin):
    """Courtrooms on staff accounts' lists (REG-35)."""

    identity_fields = ("user", "courtroom")
    fields = ("user", "courtroom", "is_active", "created_by", "updated_by", "updated_at")
    readonly_fields = ("created_by", "updated_by", "updated_at")
    list_display = ("user", "courtroom", "establishment", "is_active", "updated_at")
    list_filter = ("is_active", "courtroom__parent")
    search_fields = (
        "user__mobile_number",
        "user__name",
        "courtroom__code",
        "courtroom__name",
    )
    autocomplete_fields = ("user",)

    @admin.display(description="establishment")
    def establishment(self, obj):
        """The courtroom's establishment."""
        return obj.courtroom.parent

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Offer courtrooms only."""
        if db_field.name == "courtroom":
            kwargs["queryset"] = Organization.objects.filter(
                court_level=CourtLevel.COURTROOM, is_active=True
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """Add or remove through the services (removing also revokes the roles there)."""
        if obj.is_active:
            self._adopt(obj, services.assign_courtroom(obj.user, obj.courtroom, actor=request.user))
        else:
            services.remove_courtroom(obj.user, obj.courtroom, actor=request.user)


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(AssignmentAdminMixin, SimpleHistoryAdmin):
    """Roles held by users at establishments and courtrooms."""

    identity_fields = ("user", "organization", "role")
    fields = ("user", "organization", "role", "is_active", "created_by", "updated_by", "updated_at")
    readonly_fields = ("created_by", "updated_by", "updated_at")
    list_display = ("user", "role", "organization", "level", "is_active", "updated_at")
    list_filter = ("is_active", "role", "organization__court_level")
    search_fields = (
        "user__mobile_number",
        "user__name",
        "organization__code",
        "organization__name",
    )
    autocomplete_fields = ("user",)

    @admin.display(description="level", ordering="organization__court_level")
    def level(self, obj):
        """Whether the role is held at an establishment or a courtroom."""
        return obj.organization.get_court_level_display()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Offer court organizations and active roles only."""
        if db_field.name == "organization":
            kwargs["queryset"] = Organization.objects.filter(
                court_level__isnull=False, is_active=True
            )
        elif db_field.name == "role":
            kwargs["queryset"] = CourtRole.objects.filter(is_active=True).select_related(
                "establishment"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """Assign or revoke through the services."""
        if obj.is_active:
            saved = services.assign_role(obj.user, obj.organization, obj.role, actor=request.user)
            self._adopt(obj, saved)
        else:
            services.revoke_role(obj.user, obj.organization, obj.role, actor=request.user)


# ---------------------------------------------------------------------------
# On the User admin
# ---------------------------------------------------------------------------


class UserCourtroomInline(ReadOnlyInline):
    """The person's courtroom list."""

    model = CourtroomAssignment
    fk_name = "user"
    fields = ("courtroom", "is_active", "updated_at")
    readonly_fields = fields
    verbose_name = "courtroom (list)"
    verbose_name_plural = "Courtrooms (list)"


class UserRoleInline(ReadOnlyInline):
    """The roles the person holds."""

    model = RoleAssignment
    fk_name = "user"
    fields = ("role", "organization", "is_active", "updated_at")
    readonly_fields = fields
    verbose_name = "court role"
    verbose_name_plural = "Court roles"


def effective_court_access(user):
    """The person's effective actions per court, as read-only HTML for the User admin."""
    if user is None or user.pk is None:
        return "-"
    summary = selectors.court_access_summary(user)
    if not summary["establishments"]:
        return "No court access."

    def describe(entries):
        rendered = [
            entry if isinstance(entry, str) else f"{entry['action']} {entry['scopes']}"
            for entry in entries
        ]
        return ", ".join(rendered) or "no actions"

    rows = []
    for establishment in summary["establishments"]:
        rows.append((establishment["name"], describe(establishment["actions"])))
        for courtroom in establishment["courtrooms"]:
            rows.append(
                (f"{establishment['name']} / {courtroom['name']}", describe(courtroom["actions"]))
            )
    links = format_html(
        '<a href="{}">Courtroom list</a> · <a href="{}">Role assignments</a>',
        reverse("admin:organizations_courtroomassignment_changelist") + f"?q={user.mobile_number}",
        reverse("admin:organizations_roleassignment_changelist") + f"?q={user.mobile_number}",
    )
    table = format_html_join("", "<tr><th>{}</th><td>{}</td></tr>", rows)
    return format_html("<table>{}</table>{}", table, links)
