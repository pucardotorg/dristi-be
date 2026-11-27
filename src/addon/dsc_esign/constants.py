"""DSC eSign constants (spec 0038)."""

PROVIDER_NAME = "dsc"
PROVIDER_PATH = "addon.dsc_esign.provider.DSCESignProvider"

# Keys in the payload the browser posts to the local signing agent.
FORM_FIELD_DIGEST = "digest"
FORM_FIELD_HASH_ALGORITHM = "hash_algorithm"
FORM_FIELD_FIELD_NAME = "field_name"
FORM_FIELD_TRANSACTION_ID = "transaction_id"

TRANSACTION_ID_PREFIX = "dsc"
MAX_TRANSACTION_ID_LENGTH = 128
