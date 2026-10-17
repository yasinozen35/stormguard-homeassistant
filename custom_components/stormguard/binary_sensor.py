"""One binary sensor per shield: on = StormGuard reports a risk."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import StormGuardConfigEntry
from .const import ATTR_ACTIVE_ALERTS, ATTR_LAST_CHANGE, ATTR_LAST_CHANGE_REASON, PROFILES
from .entity import StormGuardEntity
from .tracker import ShieldTracker


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StormGuardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the four shield sensors."""
    async_add_entities(ShieldBinarySensor(entry.runtime_data, profile) for profile in PROFILES)


class ShieldBinarySensor(StormGuardEntity, BinarySensorEntity):
    """`on` while ANY `type|severity` key of the shield is active."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, tracker: ShieldTracker, profile: str) -> None:
        super().__init__(tracker, profile)
        self.profile = profile

    @property
    def is_on(self) -> bool:
        return self.tracker.is_on(self.profile)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.tracker.profiles[self.profile]
        return {
            ATTR_ACTIVE_ALERTS: [a.as_dict() for a in self.tracker.alerts(self.profile)],
            ATTR_LAST_CHANGE: state.last_change.isoformat() if state.last_change else None,
            ATTR_LAST_CHANGE_REASON: state.last_change_reason,
        }

    async def async_restore(self) -> None:
        if (last := await self.async_get_last_state()) is None:
            return
        self.tracker.async_restore_profile(
            self.profile,
            last.attributes.get(ATTR_ACTIVE_ALERTS),
            last.attributes.get(ATTR_LAST_CHANGE),
            last.attributes.get(ATTR_LAST_CHANGE_REASON),
        )
