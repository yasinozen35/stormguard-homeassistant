"""Shield state: which `type|severity` keys are active per profile.

This is the only state the integration keeps. It is *risk* state ("StormGuard
says electronics are at risk"), never device state: what a device does about
it is decided by the user's automations.

Rules (MOTTO: a missed `cleared` must never leave a device stuck):

- ``raised`` adds a key (or refreshes it) and (re)arms its safety timeout.
- ``cleared`` removes that key. The profile is "at risk" while ANY key is
  active, so a warning→critical escalation (raised critical, then cleared
  warning) keeps the shield on.
- If ``cleared`` never arrives, the safety timeout removes the key and fires
  ``stormguard_expired``.
- Timers survive restarts through the entities' restored attributes. Restored
  timers are armed only once Home Assistant has *started*, so automations are
  listening when the shield turns off — an expiry during startup would
  otherwise be an on→off transition nobody sees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    ALERT_TYPES,
    EVENT_EXPIRED,
    EVENT_STORMGUARD,
    PROFILES,
    REASON_CLEARED,
    REASON_RAISED,
    REASON_TIMEOUT,
    SEVERITIES,
    STATE_CLEARED,
    STATE_RAISED,
    signal_update,
)
from .payload import StormGuardEvent

_LOGGER = logging.getLogger(__name__)

# A restored timer that is already due fires this long after startup.
RESTORE_GRACE = timedelta(seconds=1)


@dataclass(slots=True)
class ActiveAlert:
    """One active key of a profile."""

    type: str
    severity: str
    headline: str | None
    since: datetime
    expires_at: datetime
    occurred_at: str | None = None

    @property
    def key(self) -> str:
        return f"{self.type}|{self.severity}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "headline": self.headline,
            "since": self.since.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> ActiveAlert | None:
        """Rebuild from restored attributes; anything malformed is dropped."""
        if not isinstance(data, dict):
            return None
        type_ = data.get("type")
        severity = data.get("severity")
        since = _parse(data.get("since"))
        expires_at = _parse(data.get("expires_at"))
        if type_ not in ALERT_TYPES or severity not in SEVERITIES:
            return None
        if since is None or expires_at is None:
            return None
        headline = data.get("headline")
        occurred = data.get("occurred_at")
        return cls(
            type=type_,
            severity=severity,
            headline=headline if isinstance(headline, str) else None,
            since=since,
            expires_at=expires_at,
            occurred_at=occurred if isinstance(occurred, str) else None,
        )


@dataclass(slots=True)
class LastEvent:
    """The last accepted event (for the "last event" sensor)."""

    received_at: datetime
    state: str
    profile: str | None = None
    type: str | None = None
    severity: str | None = None
    headline: str | None = None
    occurred_at: str | None = None


@dataclass(slots=True)
class ProfileState:
    """State of one shield."""

    alerts: dict[str, ActiveAlert] = field(default_factory=dict)
    last_change: datetime | None = None
    last_change_reason: str | None = None


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return dt_util.as_utc(value)
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed is not None:
            return dt_util.as_utc(parsed) if parsed.tzinfo else parsed.replace(tzinfo=dt_util.UTC)
    return None


class ShieldTracker:
    """Holds the risk state for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str, safety_timeout: timedelta) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.safety_timeout = safety_timeout
        self.profiles: dict[str, ProfileState] = {p: ProfileState() for p in PROFILES}
        self.last_event: LastEvent | None = None
        self._timers: dict[tuple[str, str], CALLBACK_TYPE] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._closed = False

    # -- queries -------------------------------------------------------------

    def is_on(self, profile: str) -> bool:
        return bool(self.profiles[profile].alerts)

    def alerts(self, profile: str) -> list[ActiveAlert]:
        return sorted(self.profiles[profile].alerts.values(), key=lambda a: a.since)

    # -- events --------------------------------------------------------------

    @callback
    def async_handle(self, event: StormGuardEvent) -> None:
        """Apply an accepted event (raised / cleared / test)."""
        now = dt_util.utcnow()
        profile_changed: str | None = None

        if event.state == STATE_RAISED and event.profile:
            state = self.profiles[event.profile]
            existing = state.alerts.get(event.key)
            alert = ActiveAlert(
                type=event.type or "",
                severity=event.severity or "",
                headline=event.headline,
                since=existing.since if existing else now,
                expires_at=now + self.safety_timeout,
                occurred_at=event.occurred_at.isoformat(),
            )
            state.alerts[event.key] = alert
            state.last_change = now
            state.last_change_reason = REASON_RAISED
            self._arm(event.profile, alert, alert.expires_at)
            profile_changed = event.profile

        elif event.state == STATE_CLEARED and event.profile:
            state = self.profiles[event.profile]
            if state.alerts.pop(event.key, None) is not None:
                self._cancel(event.profile, event.key)
                state.last_change = now
                state.last_change_reason = REASON_CLEARED
                profile_changed = event.profile

        self.last_event = LastEvent(
            received_at=now,
            state=event.state,
            profile=event.profile,
            type=event.type,
            severity=event.severity,
            headline=event.headline,
            occurred_at=event.occurred_at.isoformat(),
        )
        _LOGGER.debug(
            "Accepted %s event (profile=%s, type=%s, severity=%s, changed=%s)",
            event.state,
            event.profile,
            event.type,
            event.severity,
            profile_changed is not None,
        )
        self.hass.bus.async_fire(
            EVENT_STORMGUARD, {**event.as_event_data(), "entry_id": self.entry_id}
        )
        self._notify()

    # -- timers --------------------------------------------------------------

    @callback
    def _arm(self, profile: str, alert: ActiveAlert, when: datetime) -> None:
        self._cancel(profile, alert.key)

        @callback
        def _fire(_now: datetime) -> None:
            self._timers.pop((profile, alert.key), None)
            self._expire(profile, alert)

        self._timers[(profile, alert.key)] = async_track_point_in_utc_time(self.hass, _fire, when)

    @callback
    def _cancel(self, profile: str, key: str) -> None:
        if (unsub := self._timers.pop((profile, key), None)) is not None:
            unsub()

    @callback
    def _expire(self, profile: str, alert: ActiveAlert) -> None:
        state = self.profiles[profile]
        # Only the exact alert this timer was armed for; a newer raised has
        # replaced the object and armed its own timer.
        if state.alerts.get(alert.key) is not alert:
            return
        del state.alerts[alert.key]
        state.last_change = dt_util.utcnow()
        state.last_change_reason = REASON_TIMEOUT
        _LOGGER.debug("Safety timeout cleared %s %s", profile, alert.key)
        self.hass.bus.async_fire(
            EVENT_EXPIRED,
            {
                "entry_id": self.entry_id,
                "profile": profile,
                "type": alert.type,
                "severity": alert.severity,
                "since": alert.since.isoformat(),
                "reason": REASON_TIMEOUT,
            },
        )
        self._notify()

    # -- restore -------------------------------------------------------------

    @callback
    def async_restore_profile(
        self,
        profile: str,
        raw_alerts: Any,
        last_change: Any,
        last_change_reason: Any,
    ) -> None:
        """Restore a profile from the binary sensor's last state.

        Alerts whose timeout already passed stay active until Home Assistant
        has started and are then expired (firing ``stormguard_expired``), so
        automations see the shield turn off.
        """
        state = self.profiles[profile]
        if isinstance(raw_alerts, list):
            for raw in raw_alerts:
                if (alert := ActiveAlert.from_dict(raw)) is not None:
                    state.alerts.setdefault(alert.key, alert)
        state.last_change = _parse(last_change)
        state.last_change_reason = (
            last_change_reason if isinstance(last_change_reason, str) else None
        )

        restored = list(state.alerts.values())
        if not restored:
            return

        @callback
        def _arm_restored(_hass: HomeAssistant) -> None:
            if self._closed:
                return
            floor = dt_util.utcnow() + RESTORE_GRACE
            for alert in restored:
                # Skip alerts that were cleared or replaced meanwhile.
                if state.alerts.get(alert.key) is alert:
                    self._arm(profile, alert, max(alert.expires_at, floor))

        self._unsubs.append(async_at_started(self.hass, _arm_restored))

    @callback
    def async_restore_last_event(self, received_at: Any, attributes: dict[str, Any]) -> None:
        """Restore the "last event" sensor."""
        if self.last_event is not None:
            return
        when = _parse(received_at)
        state = attributes.get("last_state")
        if when is None or not isinstance(state, str):
            return

        def _str(name: str) -> str | None:
            value = attributes.get(name)
            return value if isinstance(value, str) else None

        self.last_event = LastEvent(
            received_at=when,
            state=state,
            profile=_str("profile"),
            type=_str("type"),
            severity=_str("severity"),
            headline=_str("headline"),
            occurred_at=_str("occurred_at"),
        )

    # -- plumbing ------------------------------------------------------------

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry_id))

    @callback
    def async_shutdown(self) -> None:
        """Cancel every timer (unload)."""
        self._closed = True
        for unsub in self._timers.values():
            unsub()
        self._timers.clear()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
