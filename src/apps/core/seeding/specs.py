"""The seedable reference-data models and their natural keys (spec 0025).

Importing this module registers every spec. The ``seed`` command imports it so
the registry is populated before it runs. Load ``order`` keeps referents ahead
of the rows that point at them (attribute definitions before the rows that use
them; locations before organizations that cite them as jurisdictions; page
categories before pages; groups and request types before approval steps).
"""

from .registry import FkRef, SeedSpec, register

# Attribute definitions load first: a row's additional_attributes are
# rejected unless each key is defined for its model (e.g. a bank's address).
register(
    SeedSpec(
        model_label="core.AdditionalAttribute",
        key=("content_type", "name"),
        fields=("name", "data_type", "is_nullable", "default_value"),
        fk_by_code={"content_type": FkRef("contenttypes.ContentType", natural_key=True)},
        order=5,
    )
)

register(
    SeedSpec(
        model_label="auth.Group",
        key=("name",),
        fields=("name",),
        order=5,
    )
)

register(
    SeedSpec(
        model_label="locations.Location",
        key=("code",),
        fields=(
            "code",
            "name",
            "short_name",
            "location_type",
            "is_active",
            "additional_attributes",
        ),
        fk_by_code={"parent": FkRef("locations.Location", "code")},
        order=10,
        # Pincodes and banks run to lakhs of rows.
        bulk=True,
    )
)

register(
    SeedSpec(
        model_label="organizations.Organization",
        key=("code",),
        fields=(
            "code",
            "organization_type",
            "name",
            "short_name",
            "description",
            "is_active",
            "additional_attributes",
            "court_level",
        ),
        fk_by_code={"parent": FkRef("organizations.Organization", "code")},
        m2m_by_code={"jurisdictions": FkRef("locations.Location", "code")},
        order=20,
    )
)

register(
    SeedSpec(
        model_label="core.BusinessRule",
        key=("code",),
        fields=(
            "code",
            "name",
            "description",
            "engine",
            "rule_expression",
            "rule_input_schema",
            "rule_output_schema",
            "is_active",
        ),
        order=30,
    )
)

register(
    SeedSpec(
        model_label="core.Configuration",
        key=("config_set", "config_key"),
        fields=("config_set", "config_key", "config_value", "description", "is_active"),
        order=30,
    )
)

register(
    SeedSpec(
        model_label="core.PublicConfiguration",
        key=("config_set", "config_key"),
        fields=(
            "config_set",
            "config_key",
            "value_type",
            "config_value",
            "description",
            "is_active",
        ),
        order=30,
    )
)

register(
    SeedSpec(
        model_label="cms.PageCategory",
        key=("slug",),
        fields=("name", "slug"),
        order=40,
    )
)

register(
    SeedSpec(
        model_label="cms.Page",
        key=("slug",),
        fields=("slug", "title", "sub_title", "main_image_url", "content_type", "content"),
        m2m_by_code={"categories": FkRef("cms.PageCategory", "slug")},
        order=50,
    )
)

register(
    SeedSpec(
        model_label="messaging.MessageTemplate",
        key=("message_key", "message_type"),
        fields=(
            "message_key",
            "message_type",
            "subject",
            "content",
            "data_schema",
            "priority",
            "category",
            "max_retries",
            "provider_template_id",
            "is_active",
        ),
        order=30,
    )
)

register(
    SeedSpec(
        model_label="hearings.HearingPurpose",
        key=("code",),
        fields=("code", "label", "description", "sequence", "is_active"),
        order=30,
    )
)

register(
    SeedSpec(
        model_label="dristi_requests.RequestType",
        key=("code",),
        fields=("code", "name", "description", "schema", "min_documents", "is_active"),
        order=30,
    )
)

# Keyed by its request type's code and step order; the group by its name.
register(
    SeedSpec(
        model_label="dristi_requests.ApprovalStep",
        key=("request_type", "order"),
        fields=("order", "approver_role", "condition"),
        fk_by_code={
            "request_type": FkRef("dristi_requests.RequestType", "code"),
            "approver_group": FkRef("auth.Group", "name"),
        },
        order=60,
    )
)

# An empty ``organization`` is the national default (matched as NULL). Loads
# after core.BusinessRule, whose code it names in ``rule_code``.
register(
    SeedSpec(
        model_label="scrutiny.ScrutinyRuleBinding",
        key=("decision", "organization"),
        fields=("decision", "rule_code", "note", "is_active"),
        fk_by_code={"organization": FkRef("organizations.Organization", "code")},
        order=60,
    )
)

# PDF templates (spec 0016) a module renders by key, e.g. the e-filing complaint.
# A used version is immutable, so a changed template is a new version row.
register(
    SeedSpec(
        model_label="pdf.PDFTemplate",
        key=("key",),
        fields=("key", "name", "description", "is_active"),
        order=30,
    )
)

register(
    SeedSpec(
        model_label="pdf.PDFTemplateVersion",
        key=("template", "version"),
        fields=("version", "format_config", "data_config", "is_active"),
        fk_by_code={"template": FkRef("pdf.PDFTemplate", "key")},
        order=40,
    )
)

register(
    SeedSpec(
        model_label="core.Language",
        key=("code",),
        fields=(
            "code",
            "name",
            "native_name",
            "is_default",
            "sort_order",
            "is_active",
            "supports",
        ),
        order=30,
    )
)

# Group membership: adds an existing user to an existing group, e.g. a
# BAR_ID_APPROVER so registration and bar-ID requests can be routed. The
# membership table, not auth.Group, is the seeded model: the groups come from
# core/auth/groups.toml, and an existing group row would be left unchanged
# (insert-only).
register(
    SeedSpec(
        model_label="users.User_groups",
        key=("user", "group"),
        fields=(),
        fk_by_code={
            "user": FkRef("users.User", "mobile_number"),
            "group": FkRef("auth.Group", "name"),
        },
        order=60,
    )
)

# Court roles (spec 0029 #4, #11). A role is keyed by its code and its
# establishment; an empty ``establishment`` is a deployment-wide role (matched
# as NULL). Seeding is insert-only, so a role's actions are seeded once and
# edited in admin afterwards.
register(
    SeedSpec(
        model_label="organizations.CourtRole",
        key=("code", "establishment"),
        fields=("code", "name", "is_active"),
        fk_by_code={"establishment": FkRef("organizations.Organization", "code")},
        order=25,
    )
)

# One action of a role, with its scope for a process action. ``role`` is the
# role's code, or ``CODE.ESTABLISHMENT_CODE`` for an establishment's own role.
# Keyed by role and action, so a scoped action listed with several scopes in
# one role is entered in admin (or the file sets ``key`` in its header).
register(
    SeedSpec(
        model_label="organizations.CourtRoleAction",
        key=("role", "action"),
        fields=("action", "scope"),
        fk_by_code={"role": FkRef("organizations.CourtRole", natural_key=True)},
        order=26,
    )
)

# Test and pilot accounts' court access (spec 0029 #11 step 3): a courtroom on
# a user's list, then a role at an establishment or a listed courtroom.
register(
    SeedSpec(
        model_label="organizations.CourtroomAssignment",
        key=("user", "courtroom"),
        fields=("is_active",),
        fk_by_code={
            "user": FkRef("users.User", "mobile_number"),
            "courtroom": FkRef("organizations.Organization", "code"),
        },
        order=61,
    )
)

register(
    SeedSpec(
        model_label="organizations.RoleAssignment",
        key=("user", "organization", "role"),
        fields=("is_active",),
        fk_by_code={
            "user": FkRef("users.User", "mobile_number"),
            "organization": FkRef("organizations.Organization", "code"),
            "role": FkRef("organizations.CourtRole", natural_key=True),
        },
        order=62,
    )
)
