"""Shared entity base."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, NAME, signal_update
from .tracker import ShieldTracker


class StormGuardEntity(RestoreEntity):
    """An entity on the single "StormGuard" device, fed by the tracker."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, tracker: ShieldTracker, key: str) -> None:
        self.tracker = tracker
        self._attr_unique_id = f"{tracker.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracker.entry_id)},
            name=NAME,
            manufacturer=NAME,
            model="Webhook",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.async_restore()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self.tracker.entry_id), self._handle_update
            )
        )

    async def async_restore(self) -> None:
        """Feed the previous state back into the tracker."""

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
