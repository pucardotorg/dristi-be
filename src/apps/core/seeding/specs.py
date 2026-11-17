"""The seedable reference-data models and their natural keys (spec 0025).

Importing this module registers every spec. The ``seed`` command imports it so
the registry is populated before it runs. Load ``order`` keeps referents ahead
of the rows that point at them (attribute definitions before the rows that use
them; locations before organizations that cite them as jurisdictions; page
categories before pages).
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
