"""Shared fixtures."""

from collections.abc import Generator
from typing import Any

from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stormguard.const import (
    CONF_ALLOW_REMOTE,
    CONF_SAFETY_TIMEOUT,
    DOMAIN,
)

WEBHOOK_ID = "stormguard_AbCdEfGhIjKlMnOpQrStUvWxYz012345"
INTERNAL_URL = "http://192.168.1.50:8123"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Load custom_components/stormguard in every test."""
    yield


@pytest.fixture
async def internal_url(hass: HomeAssistant) -> str:
    """Give hass a local URL like a real install has."""
    await async_process_ha_core_config(hass, {"internal_url": INTERNAL_URL})
    return INTERNAL_URL


def make_entry(
    *, allow_remote: bool = False, timeout: int = 120, webhook_id: str = WEBHOOK_ID
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="StormGuard",
        unique_id=DOMAIN,
        data={CONF_WEBHOOK_ID: webhook_id},
        options={CONF_ALLOW_REMOTE: allow_remote, CONF_SAFETY_TIMEOUT: timeout},
        entry_id="sg_entry",
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, key: str, entry_id: str = "sg_entry") -> str:
    """Look an entity up by unique id (independent of translated names)."""
    registry = er.async_get(hass)
    platform = "sensor" if key == "last_event" else "binary_sensor"
    found = registry.async_get_entity_id(platform, DOMAIN, f"{entry_id}_{key}")
    assert found is not None, key
    return found


def event(state: str = "raised", /, **overrides: Any) -> dict[str, Any]:
    """The app's wire payload (flat object)."""
    if state == "test":
        body: dict[str, Any] = {
            "source": "stormguard",
            "version": 1,
            "state": "test",
            "profile": None,
            "type": None,
            "severity": None,
            "headline": "StormGuard test",
            "occurredAt": "2026-10-17T10:00:00.000Z",
        }
    else:
        body = {
            "source": "stormguard",
            "version": 1,
            "state": state,
            "profile": "electronics",
            "type": "thunderstorm",
            "severity": "critical",
            "headline": "Yıldırım riski" if state == "raised" else None,
            "occurredAt": "2026-10-17T10:00:00.000Z",
        }
    body.update(overrides)
    return body
