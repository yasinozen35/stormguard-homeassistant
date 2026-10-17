""" "Last event" sensor — when the app last reached Home Assistant."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StormGuardConfigEntry
from .entity import StormGuardEntity
from .tracker import ShieldTracker


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StormGuardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the last-event sensor."""
    async_add_entities([LastEventSensor(entry.runtime_data)])


class LastEventSensor(StormGuardEntity, SensorEntity):
    """Timestamp of the last accepted event; also updated by `test` events."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, tracker: ShieldTracker) -> None:
        super().__init__(tracker, "last_event")

    @property
    def native_value(self) -> datetime | None:
        event = self.tracker.last_event
        return event.received_at if event else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = self.tracker.last_event
        if event is None:
            return {}
        return {
            "last_state": event.state,
            "profile": event.profile,
            "type": event.type,
            "severity": event.severity,
            "headline": event.headline,
            "occurred_at": event.occurred_at,
        }

    async def async_restore(self) -> None:
        if (last := await self.async_get_last_state()) is None:
            return
        self.tracker.async_restore_last_event(last.state, dict(last.attributes))
