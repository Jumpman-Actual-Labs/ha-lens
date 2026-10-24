"""Constants for the Lens integration."""

DOMAIN = "lens"
API_ID = "lens"
API_NAME = "Lens"

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_HIDDEN = "hidden"
STATUS_NOT_LOADED = "not_loaded"
STATUS_NOT_IN_REGISTRY = "not_in_registry"

STATUSES = (
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_HIDDEN,
    STATUS_NOT_LOADED,
    STATUS_NOT_IN_REGISTRY,
)

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
MAX_LIMIT_IDS_ONLY = 5000
