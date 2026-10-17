"""Validation of the StormGuard webhook payload — pure, no Home Assistant state.

Contract (flat JSON object, POST /api/webhook/<id>):

    source      "stormguard"                                   required
    version     integer >= 1 (newer versions accepted)        required
    state       "raised" | "cleared" | "test"                 required
    profile     electronics | car | plants | clothes          raised/cleared
    type        rain | thunderstorm | wind | hail | frost     raised/cleared
    severity    critical | warning                            raised/cleared
    headline    string | null (<= 500 chars)                  optional
    occurredAt  ISO-8601                                       required

Unknown fields are ignored. An unknown `state` string is *ignored* (not an
error) so a future app version cannot break an older integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    ALERT_TYPES,
    KNOWN_STATES,
    MAX_HEADLINE_LENGTH,
    PROFILES,
    SEVERITIES,
    SOURCE,
    STATE_TEST,
)


class InvalidPayload(ValueError):
    """The body is not a valid StormGuard event (answered with HTTP 400)."""


@dataclass(frozen=True, slots=True)
class StormGuardEvent:
    """A validated event."""

    version: int
    state: str
    profile: str | None
    type: str | None
    severity: str | None
    headline: str | None
    occurred_at: datetime

    @property
    def key(self) -> str:
        """Dedup key within a profile — same as the app's `type|severity`."""
        return f"{self.type}|{self.severity}"

    def as_event_data(self) -> dict[str, Any]:
        """Payload re-published on the bus (wire field names)."""
        return {
            "source": SOURCE,
            "version": self.version,
            "state": self.state,
            "profile": self.profile,
            "type": self.type,
            "severity": self.severity,
            "headline": self.headline,
            "occurredAt": self.occurred_at.isoformat(),
        }


def _require_choice(body: dict[str, Any], field: str, choices: tuple[str, ...]) -> str:
    value = body.get(field)
    if not isinstance(value, str) or value not in choices:
        raise InvalidPayload(f"invalid {field}")
    return value


def parse_event(body: Any) -> StormGuardEvent | None:
    """Validate a decoded JSON body.

    Returns the event, or ``None`` when the body is valid but carries a
    ``state`` this version does not know (ignored). Raises
    :class:`InvalidPayload` otherwise.
    """
    if not isinstance(body, dict):
        raise InvalidPayload("body must be a JSON object")

    if body.get("source") != SOURCE:
        raise InvalidPayload("invalid source")

    version = body.get("version")
    # `bool` is an `int` subclass; `true` is not a version.
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise InvalidPayload("invalid version")

    state = body.get("state")
    if not isinstance(state, str) or not state:
        raise InvalidPayload("invalid state")

    occurred_raw = body.get("occurredAt")
    occurred_at = dt_util.parse_datetime(occurred_raw) if isinstance(occurred_raw, str) else None
    if occurred_at is None:
        raise InvalidPayload("invalid occurredAt")
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=dt_util.UTC)

    headline = body.get("headline")
    if headline is not None and not isinstance(headline, str):
        raise InvalidPayload("invalid headline")
    if headline is not None:
        headline = headline[:MAX_HEADLINE_LENGTH]

    if state not in KNOWN_STATES:
        return None

    if state == STATE_TEST:
        # A test carries no shield/type/severity; anything sent there is ignored.
        return StormGuardEvent(version, state, None, None, None, headline, occurred_at)

    return StormGuardEvent(
        version=version,
        state=state,
        profile=_require_choice(body, "profile", PROFILES),
        type=_require_choice(body, "type", ALERT_TYPES),
        severity=_require_choice(body, "severity", SEVERITIES),
        headline=headline,
        occurred_at=occurred_at,
    )
