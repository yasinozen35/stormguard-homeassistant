"""The README's YAML examples run as real automations.

Blocks are found by their `# stormguard-example: <name>` marker, so the
documentation cannot drift from what actually works.
"""

from datetime import timedelta
from pathlib import Path
import re
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)
import yaml

from .conftest import WEBHOOK_ID, event, make_entry, setup_entry
from .test_blueprints import copy_blueprints, settle

README = Path(__file__).parents[1] / "README.md"
URL = f"/api/webhook/{WEBHOOK_ID}"


def example(name: str) -> dict[str, Any]:
    blocks = re.findall(r"```yaml\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
    for block in blocks:
        if f"# stormguard-example: {name}\n" in block:
            config = yaml.safe_load(block.replace("stormguard_ORNEK_KIMLIK", WEBHOOK_ID))
            config["id"] = name
            return config
    raise AssertionError(f"README example {name!r} not found")


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    return hass_tmp_config_dir


async def test_webhook_test_notification_shares_id_with_blueprint(
    hass: HomeAssistant, hass_client_no_auth: Any
) -> None:
    """Example A: a test-notification automation next to a blueprint, same id."""
    assert await async_setup_component(hass, "webhook", {})
    hass.states.async_set("switch.modem", "on")
    notify = async_mock_service(hass, "persistent_notification", "create")
    off = async_mock_service(hass, "switch", "turn_off")

    copy_blueprints(hass)
    guard = {
        "id": "guard",
        "alias": "guard",
        "use_blueprint": {
            "path": "stormguard/switch_guard.yaml",
            "input": {"webhook_id": WEBHOOK_ID, "switches": ["switch.modem"]},
        },
    }
    assert await async_setup_component(
        hass, "automation", {"automation": [guard, example("webhook-test-notification")]}
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()

    await client.post(URL, json=event("test"))
    await settle()
    assert len(notify) == 1
    assert "StormGuard test" in notify[0].data["message"]
    assert off == []

    await client.post(URL, json=event("raised"))
    await settle()
    assert len(off) == 1
    assert len(notify) == 1  # raised is not a test


async def test_integration_modem_example(
    hass: HomeAssistant,
    hass_client_no_auth: Any,
    internal_url: str,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Example B: binary-sensor automation — raised, cleared and timeout."""
    freezer.move_to("2026-10-17 10:00:00+00:00")
    await setup_entry(hass, make_entry(timeout=60))
    off = async_mock_service(hass, "switch", "turn_off")
    on = async_mock_service(hass, "switch", "turn_on")
    assert await async_setup_component(
        hass, "automation", {"automation": [example("integration-modem")]}
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()

    await client.post(URL, json=event("raised"))
    await hass.async_block_till_done()
    assert (len(off), len(on)) == (1, 0)
    await client.post(URL, json=event("test"))
    await hass.async_block_till_done()
    assert (len(off), len(on)) == (1, 0)
    await client.post(URL, json=event("cleared"))
    await hass.async_block_till_done()
    assert (len(off), len(on)) == (1, 1)

    # Missed cleared: the safety timeout turns the modem back on.
    await client.post(URL, json=event("raised"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert (len(off), len(on)) == (2, 2)


async def test_integration_test_notification_example(
    hass: HomeAssistant, hass_client_no_auth: Any, internal_url: str
) -> None:
    await setup_entry(hass, make_entry())
    notify = async_mock_service(hass, "persistent_notification", "create")
    assert await async_setup_component(
        hass, "automation", {"automation": [example("integration-test-notification")]}
    )
    await hass.async_block_till_done()
    client = await hass_client_no_auth()
    await client.post(URL, json=event("raised"))
    await client.post(URL, json=event("test"))
    await hass.async_block_till_done()
    assert len(notify) == 1
    assert notify[0].data["message"] == "Test olayı ulaştı: StormGuard test"


async def test_blueprint_after_integration_same_id(
    hass: HomeAssistant, internal_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Documented conflict: the integration keeps the id, the automation fails."""
    entry = await setup_entry(hass, make_entry())
    copy_blueprints(hass)
    guard = {
        "id": "guard",
        "alias": "guard",
        "use_blueprint": {
            "path": "stormguard/switch_guard.yaml",
            "input": {"webhook_id": WEBHOOK_ID, "switches": ["switch.modem"]},
        },
    }
    assert await async_setup_component(hass, "automation", {"automation": [guard]})
    await hass.async_block_till_done()
    # The integration keeps working; the automation's trigger fails with the
    # message the README tells users to look for.
    assert entry.state is ConfigEntryState.LOADED
    assert "Handler is already defined!" in caplog.text
