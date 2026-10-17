"""packages/stormguard.yaml — the climate_guard memory helper, ready to drop in.

Promises: max 255 (HA's ceiling, UI default is 100), and **no** ``initial`` so
the value survives a Home Assistant restart — that restart is exactly when the
memory is needed (storm, power cut). Also checked end to end: climate_guard
writes into this very helper and restores from it after a restart.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.climate import HVACMode
from homeassistant.components.input_text import DOMAIN as INPUT_TEXT
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache,
    setup_test_component_platform,
)
import yaml

from .test_blueprints import Harness, copy_blueprints, payload, settle
from .test_climate_guard import FakeAC, guard_config

PACKAGE = Path(__file__).parent.parent / "packages" / "stormguard.yaml"
ENTITY = "input_text.stormguard_klima_hafiza"


def _config() -> dict:
    return yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))


def test_package_shape() -> None:
    helper = _config()[INPUT_TEXT]["stormguard_klima_hafiza"]
    assert helper["max"] == 255
    assert helper.get("min", 0) == 0
    assert "initial" not in helper, "initial would wipe the memory on every restart"
    assert "pattern" not in helper


async def test_package_creates_helper(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, INPUT_TEXT, _config())
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes["max"] == 255
    assert state.attributes["mode"] == "text"


async def test_value_survives_restart(hass: HomeAssistant) -> None:
    record = (
        "d=1792300000;climate.salon=cool/24/auto;"
        "climate.yatak=cool/23/low;climate.cocuk=dry/25/auto"
    )
    mock_restore_cache(hass, (State(ENTITY, record),))
    assert await async_setup_component(hass, INPUT_TEXT, _config())
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == record


@pytest.mark.parametrize("length", [100, 255])
async def test_accepts_up_to_255(hass: HomeAssistant, length: int) -> None:
    assert await async_setup_component(hass, INPUT_TEXT, _config())
    await hass.async_block_till_done()
    value = "x" * length
    await hass.services.async_call(
        INPUT_TEXT, "set_value", {"entity_id": ENTITY, "value": value}, blocking=True
    )
    assert hass.states.get(ENTITY).state == value


# ---------------------------------------------------------------------------
# End to end: climate_guard using exactly this package's helper
# ---------------------------------------------------------------------------


async def _setup(hass: HomeAssistant, acs: dict[str, FakeAC]) -> None:
    assert await async_setup_component(hass, "webhook", {})
    assert await async_setup_component(hass, "scene", {})
    assert await async_setup_component(hass, INPUT_TEXT, _config())
    setup_test_component_platform(hass, "climate", list(acs.values()))
    assert await async_setup_component(hass, "climate", {"climate": {"platform": "test"}})
    await hass.async_block_till_done()


def _three_acs(running: bool) -> dict[str, FakeAC]:
    """The user's home: 1× Daikin Shira Plus (Onecta) + 2× Kaira Plus (Midea)."""
    mode = HVACMode.COOL if running else HVACMode.OFF
    return {
        "climate.shira_salon": FakeAC("shira_salon", mode, 24.0, "auto"),
        "climate.kaira_yatak": FakeAC("kaira_yatak", mode, 23.0, "low"),
        "climate.kaira_cocuk": FakeAC(
            "kaira_cocuk", HVACMode.DRY if running else HVACMode.OFF, 25.0, "auto"
        ),
    }


async def test_storm_cycle_uses_package_helper(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-10-17 10:00:00+00:00")
    acs = _three_acs(running=True)
    await _setup(hass, acs)
    copy_blueprints(hass)
    assert await async_setup_component(
        hass, "automation", {"automation": [guard_config(acs, memory=ENTITY)]}
    )
    await hass.async_block_till_done()
    h = Harness(hass, await hass_client_no_auth(), freezer)

    await h.post(payload("raised", severity="critical"))
    assert all(ac.settings()[0] == "off" for ac in acs.values())
    stored = hass.states.get(ENTITY).state
    assert stored.startswith("d=") and len(stored) <= 255
    for entity_id in acs:
        assert entity_id in stored  # all three fit with full settings in 255

    await h.post(payload("cleared", severity="critical"))
    assert acs["climate.shira_salon"].settings()[:3] == ("cool", 24.0, "auto")
    assert acs["climate.kaira_yatak"].settings()[:3] == ("cool", 23.0, "low")
    assert acs["climate.kaira_cocuk"].settings()[:3] == ("dry", 25.0, "auto")
    assert hass.states.get(ENTITY).state == ""


async def test_power_cut_restart_restores_from_package_helper(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    """Storm, power cut, HA comes back after the deadline: ACs come back on."""
    now = dt_util.parse_datetime("2026-10-17 12:00:00+00:00")
    freezer.move_to(now)
    deadline = int((now - timedelta(minutes=30)).timestamp())
    stored = (
        f"d={deadline};climate.shira_salon=cool/24/auto;"
        "climate.kaira_yatak=cool/23/low;climate.kaira_cocuk=dry/25/auto"
    )
    mock_restore_cache(
        hass,
        (
            State(ENTITY, stored),
            State(
                "automation.klima",
                "on",
                {"last_triggered": (now - timedelta(minutes=90)).isoformat()},
            ),
        ),
    )
    hass.set_state(CoreState.not_running)
    acs = _three_acs(running=False)
    await _setup(hass, acs)
    copy_blueprints(hass)
    assert await async_setup_component(
        hass, "automation", {"automation": [guard_config(acs, memory=ENTITY)]}
    )
    await hass.async_start()
    await settle()

    assert acs["climate.shira_salon"].settings()[:3] == ("cool", 24.0, "auto")
    assert acs["climate.kaira_yatak"].settings()[:3] == ("cool", 23.0, "low")
    assert acs["climate.kaira_cocuk"].settings()[:3] == ("dry", 25.0, "auto")
    assert hass.states.get(ENTITY).state == ""
