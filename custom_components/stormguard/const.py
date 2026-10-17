"""Constants for StormGuard.

The wire contract lives in the StormGuard app
(`src/domain/integrations/automationEvents.ts`). This integration only
*listens*: the app publishes facts ("risk started", "risk ended"), Home
Assistant decides what devices do. There is deliberately no command field and
no entity id anywhere in the payload.
"""

from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "stormguard"
NAME: Final = "StormGuard"

SOURCE: Final = "stormguard"

PROFILES: Final = ("electronics", "car", "plants", "clothes")
ALERT_TYPES: Final = ("rain", "thunderstorm", "wind", "hail", "frost")
SEVERITIES: Final = ("critical", "warning")

STATE_RAISED: Final = "raised"
STATE_CLEARED: Final = "cleared"
STATE_TEST: Final = "test"
KNOWN_STATES: Final = (STATE_RAISED, STATE_CLEARED, STATE_TEST)

# Reasons recorded in `last_change_reason`.
REASON_RAISED: Final = "raised"
REASON_CLEARED: Final = "cleared"
REASON_TIMEOUT: Final = "timeout"

CONF_ALLOW_REMOTE: Final = "allow_remote"
CONF_SAFETY_TIMEOUT: Final = "safety_timeout_minutes"

DEFAULT_ALLOW_REMOTE: Final = False
DEFAULT_SAFETY_TIMEOUT: Final = 120
MIN_SAFETY_TIMEOUT: Final = 10
MAX_SAFETY_TIMEOUT: Final = 720

EVENT_STORMGUARD: Final = "stormguard_event"
EVENT_EXPIRED: Final = "stormguard_expired"

# Same alphabet the app accepts (`SAFE_WEBHOOK_ID` in homeAssistantConfig.ts).
WEBHOOK_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
WEBHOOK_ID_PREFIX: Final = "stormguard_"

MAX_HEADLINE_LENGTH: Final = 500
MAX_BODY_BYTES: Final = 16 * 1024

APP_PAIRING_URL: Final = "stormguardweather://home-assistant"

ATTR_ACTIVE_ALERTS: Final = "active_alerts"
ATTR_LAST_CHANGE: Final = "last_change"
ATTR_LAST_CHANGE_REASON: Final = "last_change_reason"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal fired when the tracked state changes."""
    return f"{DOMAIN}_update_{entry_id}"
