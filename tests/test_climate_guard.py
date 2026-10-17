"""climate_guard blueprint — real climate entities, real scene/input_text.

The ACs are real `ClimateEntity` objects (like Daikin Onecta / Midea): they
change state when a service is called and log every call, so the tests can
assert both the final settings and *how* they were reached (e.g. never a bare
`climate.turn_on`).
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache,
    setup_test_component_platform,
)

from .test_blueprints import WEBHOOK_ID, Harness, copy_blueprints, payload, settle

MEMORY = "input_text.sg_memory"
NOW = "2026-10-17 10:00:00+00:00"


class FakeAC(ClimateEntity):
    """A split AC: cool/heat/dry/fan/auto, target temperature, fan, swing."""

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5

    def __init__(
        self,
        name: str,
        mode: HVACMode,
        temp: float | None = 24.0,
        fan: str | None = "auto",
        *,
        swing: str | None = "off",
        available: bool = True,
        turn_off_feature: bool = True,
    ) -> None:
        self._attr_name = name
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
            HVACMode.AUTO,
        ]
        self._attr_fan_modes = ["auto", "low", "medium", "high", "quiet"]
        self._attr_swing_modes = ["off", "vertical", "both"]
        self._attr_unique_id = name
        self._attr_hvac_mode = mode
        self._attr_target_temperature = temp
        self._attr_fan_mode = fan
        self._attr_swing_mode = swing
        self._attr_available = available
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.TURN_ON
        )
        if turn_off_feature:
            features |= ClimateEntityFeature.TURN_OFF
        self._attr_supported_features = features
        self.calls: list[tuple[str, Any]] = []

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.calls.append(("set_hvac_mode", str(hvac_mode)))
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        self.calls.append(("set_temperature", kwargs.get(ATTR_TEMPERATURE)))
        self._attr_target_temperature = kwargs.get(ATTR_TEMPERATURE)
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self.calls.append(("set_fan_mode", fan_mode))
        self._attr_fan_mode = fan_mode
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self.calls.append(("set_swing_mode", swing_mode))
        self._attr_swing_mode = swing_mode
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        # What a real "fake turn on" may do: pick the first mode it knows.
        self.calls.append(("turn_on", None))
        self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        self.calls.append(("turn_off", None))
        self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    def settings(self) -> tuple[str, float | None, str | None, str | None]:
        return (
            str(self._attr_hvac_mode),
            self._attr_target_temperature,
            self._attr_fan_mode,
            self._attr_swing_mode,
        )


def default_acs() -> dict[str, FakeAC]:
    return {
        "climate.salon": FakeAC("salon", HVACMode.COOL, 22.5, "quiet", swing="both"),
        "climate.yatak": FakeAC("yatak", HVACMode.DRY, 25.0, "low"),
        "climate.cocuk": FakeAC("cocuk", HVACMode.OFF, 21.0, "auto"),  # user had it off
    }


async def setup_world(
    hass: HomeAssistant,
    acs: dict[str, FakeAC],
    *,
    memory_max: int | None = 255,
) -> None:
    assert await async_setup_component(hass, "webhook", {})
    assert await async_setup_component(hass, "scene", {})
    if memory_max is not None:
        assert await async_setup_component(
            hass, "input_text", {"input_text": {"sg_memory": {"max": memory_max}}}
        )
    setup_test_component_platform(hass, "climate", list(acs.values()))
    assert await async_setup_component(hass, "climate", {"climate": {"platform": "test"}})
    await hass.async_block_till_done()
    for entity_id in acs:
        assert hass.states.get(entity_id) is not None, entity_id


def guard_config(acs: dict[str, FakeAC], alias: str = "klima", **inputs: Any) -> dict[str, Any]:
    return {
        "id": alias,
        "alias": alias,
        "use_blueprint": {
            "path": "stormguard/climate_guard.yaml",
            "input": {
                "webhook_id": WEBHOOK_ID,
                "climates": list(acs),
                "safety_minutes": 60,
                **inputs,
            },
        },
    }


async def start_guard(hass: HomeAssistant, *configs: dict[str, Any]) -> None:
    copy_blueprints(hass)
    assert await async_setup_component(hass, "automation", {"automation": list(configs)})
    await hass.async_block_till_done()
    for config in configs:
        state = hass.states.get(f"automation.{config['alias']}")
        assert state is not None
        assert state.state == "on"


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    return hass_tmp_config_dir


@pytest.fixture
async def world(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> Callable[..., Any]:
    """Build hass with ACs, scene, memory helper and one climate_guard."""
    freezer.move_to(NOW)

    async def _world(
        acs: dict[str, FakeAC] | None = None, memory_max: int | None = 255, **inputs: Any
    ) -> tuple[Harness, dict[str, FakeAC]]:
        acs = acs if acs is not None else default_acs()
        await setup_world(hass, acs, memory_max=memory_max)
        if memory_max is not None:
            inputs.setdefault("memory", MEMORY)
        await start_guard(hass, guard_config(acs, **inputs))
        return Harness(hass, await hass_client_no_auth(), freezer), acs

    return _world


def memory(hass: HomeAssistant) -> str:
    return hass.states.get(MEMORY).state


def no_bare_turn_on(acs: dict[str, FakeAC]) -> None:
    for ac in acs.values():
        assert ("turn_on", None) not in ac.calls, ac.calls


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


async def test_raised_turns_off_only_running_acs(world: Callable[..., Any]) -> None:
    h, acs = await world()
    assert await h.post(payload("raised")) == 200

    assert acs["climate.salon"].settings()[0] == "off"
    assert acs["climate.yatak"].settings()[0] == "off"
    assert acs["climate.salon"].calls == [("set_hvac_mode", "off")]
    # The AC the user had off is never touched.
    assert acs["climate.cocuk"].calls == []
    # One snapshot scene per AC that was on.
    assert h.hass.states.get("scene.stormguard_klima_salon") is not None
    assert h.hass.states.get("scene.stormguard_klima_yatak") is not None
    assert h.hass.states.get("scene.stormguard_klima_cocuk") is None


async def test_cleared_restores_exact_settings_via_scene(world: Callable[..., Any]) -> None:
    h, acs = await world()
    before = {e: ac.settings() for e, ac in acs.items()}
    await h.post(payload("raised"))
    await h.advance(5)
    await h.post(payload("cleared"))
    await settle()

    for entity_id, ac in acs.items():
        assert ac.settings() == before[entity_id], entity_id
    assert acs["climate.cocuk"].calls == []
    no_bare_turn_on(acs)
    # Scene path: reproduce_state replays mode, temperature, fan and swing.
    assert ("set_swing_mode", "both") in acs["climate.salon"].calls
    # Clean-up: snapshot scenes and memory are gone.
    assert h.hass.states.get("scene.stormguard_klima_salon") is None
    assert memory(h.hass) == ""
    assert h.hass.states.get("automation.klima").attributes["current"] == 0


async def test_memory_record_written(world: Callable[..., Any]) -> None:
    h, _acs = await world()
    await h.post(payload("raised"))
    deadline = int(dt_util.parse_datetime(NOW).timestamp()) + 3600
    assert memory(h.hass) == (
        f"d={deadline};climate.salon=cool/22.5/quiet;climate.yatak=dry/25/low"
    )


async def test_escalation_does_not_restore_mid_storm(world: Callable[..., Any]) -> None:
    """warning → critical arrives as raised(critical) + cleared(warning)."""
    h, acs = await world()
    await h.post(payload("raised", severity="warning"))
    await h.advance(10)
    await h.post(payload("raised", severity="critical"))
    await h.post(payload("cleared", severity="warning"))
    assert acs["climate.salon"].settings()[0] == "off"
    assert acs["climate.yatak"].settings()[0] == "off"

    await h.post(payload("cleared", severity="critical"))
    assert acs["climate.salon"].settings()[0] == "cool"
    assert acs["climate.yatak"].settings()[0] == "dry"


async def test_two_keys_same_profile(world: Callable[..., Any]) -> None:
    h, acs = await world()
    await h.post(payload("raised", type="thunderstorm"))
    await h.post(payload("raised", type="wind", severity="warning"))
    await h.post(payload("cleared", type="thunderstorm"))
    assert acs["climate.salon"].settings()[0] == "off"
    await h.post(payload("cleared", type="wind", severity="warning"))
    assert acs["climate.salon"].settings()[0] == "cool"


async def test_safety_timeout_restores(world: Callable[..., Any]) -> None:
    h, acs = await world(safety_minutes=30)
    await h.post(payload("raised"))
    await h.advance(29)
    assert acs["climate.salon"].settings()[0] == "off"
    await h.advance(2)
    assert acs["climate.salon"].settings() == ("cool", 22.5, "quiet", "both")
    assert memory(h.hass) == ""
    no_bare_turn_on(acs)


async def test_reraise_extends_timeout(world: Callable[..., Any]) -> None:
    h, acs = await world(safety_minutes=30)
    await h.post(payload("raised", severity="warning"))
    await h.advance(20)
    await h.post(payload("raised", severity="critical"))
    await h.advance(20)
    assert acs["climate.salon"].settings()[0] == "off"
    await h.advance(11)
    assert acs["climate.salon"].settings()[0] == "cool"


async def test_user_turned_on_meanwhile_is_not_overridden(
    world: Callable[..., Any],
) -> None:
    h, acs = await world()
    await h.post(payload("raised"))
    # The user turns the bedroom AC back on during the storm, in heat mode.
    await h.hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.yatak", "hvac_mode": "heat"},
        blocking=True,
    )
    calls_before = list(acs["climate.yatak"].calls)
    await h.post(payload("cleared"))
    await settle()

    assert acs["climate.yatak"].settings()[0] == "heat"
    assert acs["climate.yatak"].calls == calls_before
    assert acs["climate.salon"].settings() == ("cool", 22.5, "quiet", "both")


async def test_unavailable_ac_is_ignored(world: Callable[..., Any]) -> None:
    acs = default_acs()
    acs["climate.balkon"] = FakeAC("balkon", HVACMode.COOL, available=False)
    h, acs = await world(acs)
    await h.post(payload("raised"))
    await h.post(payload("cleared"))
    await settle()
    assert acs["climate.balkon"].calls == []
    assert "balkon" not in memory(h.hass)


async def test_ac_without_turn_off_feature_is_still_turned_off(
    world: Callable[..., Any],
) -> None:
    """`climate.turn_off` needs TURN_OFF; `set_hvac_mode: off` does not."""
    acs = {"climate.eski": FakeAC("eski", HVACMode.COOL, turn_off_feature=False)}
    h, acs = await world(acs)
    await h.post(payload("raised"))
    assert acs["climate.eski"].settings()[0] == "off"
    await h.post(payload("cleared"))
    assert acs["climate.eski"].settings()[0] == "cool"


async def test_all_acs_already_off_does_nothing(world: Callable[..., Any]) -> None:
    acs = {"climate.cocuk": FakeAC("cocuk", HVACMode.OFF)}
    h, acs = await world(acs)
    await h.post(payload("raised"))
    await h.post(payload("cleared"))
    await h.advance(120)
    assert acs["climate.cocuk"].calls == []
    assert memory(h.hass) in ("", "unknown")


@pytest.mark.parametrize(
    "body",
    [
        payload("test"),
        payload("raised", profile="car", type="hail"),
        payload("raised", source="other"),
        payload("raised", severity="info"),
        payload("unknown_future_state"),
    ],
    ids=["test", "other-profile", "wrong-source", "info", "unknown-state"],
)
async def test_events_that_change_nothing(world: Callable[..., Any], body: Any) -> None:
    h, acs = await world()
    assert await h.post(body) == 200
    for ac in acs.values():
        assert ac.calls == []


async def test_test_event_mid_session_changes_nothing(world: Callable[..., Any]) -> None:
    h, acs = await world()
    await h.post(payload("raised"))
    await h.post(payload("test"))
    await h.post(payload("cleared", profile="car", type="hail"))
    assert acs["climate.salon"].settings()[0] == "off"


async def test_below_min_severity(world: Callable[..., Any]) -> None:
    h, acs = await world(min_severity="critical")
    await h.post(payload("raised", severity="warning"))
    assert acs["climate.salon"].calls == []


async def test_without_memory_helper(world: Callable[..., Any]) -> None:
    """Memory is optional: the in-run scene restore works without it."""
    h, acs = await world(memory_max=None)
    await h.post(payload("raised"))
    await h.post(payload("cleared"))
    await settle()
    assert acs["climate.salon"].settings() == ("cool", 22.5, "quiet", "both")


async def test_scene_missing_falls_back_to_record(world: Callable[..., Any]) -> None:
    """If the snapshot scene is gone, the recorded mode/temp/fan are used."""
    h, acs = await world()
    await h.post(payload("raised"))
    await h.hass.services.async_call(
        "scene", "delete", {"entity_id": "scene.stormguard_klima_salon"}, blocking=True
    )
    await h.post(payload("cleared"))
    await settle()
    assert acs["climate.salon"].settings()[:3] == ("cool", 22.5, "quiet")
    assert acs["climate.salon"].calls[-3:] == [
        ("set_hvac_mode", "cool"),
        ("set_temperature", 22.5),
        ("set_fan_mode", "quiet"),
    ]
    no_bare_turn_on(acs)


async def test_shares_webhook_id_with_switch_guard(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOW)
    acs = default_acs()
    await setup_world(hass, acs)
    hass.states.async_set("switch.modem", "on")
    from pytest_homeassistant_custom_component.common import async_mock_service  # noqa: PLC0415

    off = async_mock_service(hass, "switch", "turn_off")
    on = async_mock_service(hass, "switch", "turn_on")
    modem = {
        "id": "modem",
        "alias": "modem",
        "use_blueprint": {
            "path": "stormguard/switch_guard.yaml",
            "input": {"webhook_id": WEBHOOK_ID, "switches": ["switch.modem"]},
        },
    }
    await start_guard(hass, guard_config(acs, memory=MEMORY), modem)
    h = Harness(hass, await hass_client_no_auth(), freezer)

    await h.post(payload("raised"))
    assert len(off) == 1
    assert acs["climate.salon"].settings()[0] == "off"
    await h.post(payload("cleared"))
    await settle()
    assert len(on) == 1
    assert acs["climate.salon"].settings()[0] == "cool"


# ---------------------------------------------------------------------------
# Memory size limit
# ---------------------------------------------------------------------------


def many_acs(count: int) -> dict[str, FakeAC]:
    return {
        f"climate.oda_{i:02d}": FakeAC(f"oda_{i:02d}", HVACMode.COOL, 23.5, "medium")
        for i in range(count)
    }


@pytest.mark.parametrize(
    ("count", "memory_max", "expect"),
    [
        (3, 255, "full"),  # mode/temp/fan for everyone
        (3, 100, "no-fan"),  # fan dropped first
        (3, 75, "no-temp"),  # then temperature
        (9, 255, "no-fan"),
        (20, 255, "partial"),  # mode only, as many ACs as fit
        (3, 10, "empty"),  # not even the header fits
    ],
)
async def test_memory_never_exceeds_limit(
    world: Callable[..., Any], count: int, memory_max: int, expect: str
) -> None:
    h, acs = await world(many_acs(count), memory_max=memory_max)
    await h.post(payload("raised"))
    value = memory(h.hass)
    assert value not in ("unknown",)
    assert len(value) <= memory_max
    entries = value.split(";")[1:] if value else []
    if expect == "full":
        assert all(e.endswith("=cool/23.5/medium") for e in entries)
        assert len(entries) == count
    elif expect == "no-fan":
        assert all(e.endswith("=cool/23.5") for e in entries)
        assert len(entries) == count
    elif expect == "no-temp":
        assert all(e.endswith("=cool") for e in entries)
        assert len(entries) == count
    elif expect == "partial":
        assert all(e.endswith("=cool") for e in entries)
        assert 0 < len(entries) < count
    else:
        assert value == ""
    # Whatever happens to memory, the in-run restore is unaffected.
    await h.post(payload("cleared"))
    await settle(50 * count)  # ~10 script steps per AC
    assert all(ac.settings()[0] == "cool" for ac in acs.values())


async def test_default_input_text_max_100_is_respected(world: Callable[..., Any]) -> None:
    """A UI-created Text helper defaults to max 100, not 255."""
    acs = default_acs()
    h, acs = await world(acs, memory_max=100)
    await h.post(payload("raised"))
    assert 0 < len(memory(h.hass)) <= 100


# ---------------------------------------------------------------------------
# Home Assistant restart
# ---------------------------------------------------------------------------


async def boot(
    hass: HomeAssistant,
    client_factory: Any,
    freezer: FrozenDateTimeFactory,
    acs: dict[str, FakeAC],
    *,
    memory_value: str | None,
    last_triggered_minutes_ago: float = 10,
    **inputs: Any,
) -> Harness:
    """Start hass as after a restart (snapshot scenes are gone)."""
    now = dt_util.parse_datetime("2026-10-17 12:00:00+00:00")
    freezer.move_to(now)
    restored = [
        State(
            "automation.klima",
            "on",
            {"last_triggered": (now - timedelta(minutes=last_triggered_minutes_ago)).isoformat()},
        )
    ]
    if memory_value is not None:
        restored.append(State(MEMORY, memory_value))
    mock_restore_cache(hass, restored)
    hass.set_state(CoreState.not_running)
    await setup_world(hass, acs, memory_max=255 if memory_value is not None else None)
    if memory_value is not None:
        inputs.setdefault("memory", MEMORY)
    copy_blueprints(hass)
    assert await async_setup_component(
        hass, "automation", {"automation": [guard_config(acs, **inputs)]}
    )
    await hass.async_start()
    await settle()
    return Harness(hass, await client_factory(), freezer)


def off_acs() -> dict[str, FakeAC]:
    """After the storm started: both running ACs were turned off by us."""
    return {
        "climate.salon": FakeAC("salon", HVACMode.OFF, 22.5, "quiet"),
        "climate.yatak": FakeAC("yatak", HVACMode.OFF, 25.0, "low"),
        "climate.cocuk": FakeAC("cocuk", HVACMode.OFF, 21.0, "auto"),
    }


def record(deadline_minutes_from_now: float) -> str:
    now = dt_util.parse_datetime("2026-10-17 12:00:00+00:00")
    deadline = int((now + timedelta(minutes=deadline_minutes_from_now)).timestamp())
    return f"d={deadline};climate.salon=cool/22.5/quiet;climate.yatak=dry/25/low"


async def test_restart_with_memory_resumes(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    acs = off_acs()
    h = await boot(hass, hass_client_no_auth, freezer, acs, memory_value=record(50))
    assert all(ac.calls == [] for ac in acs.values())
    await h.advance(49)
    assert acs["climate.salon"].settings()[0] == "off"
    await h.advance(2)
    assert acs["climate.salon"].settings()[:3] == ("cool", 22.5, "quiet")
    assert acs["climate.yatak"].settings()[:3] == ("dry", 25.0, "low")
    assert acs["climate.cocuk"].calls == []  # not in memory: the user's own
    assert memory(hass) == ""
    no_bare_turn_on(acs)


async def test_restart_with_memory_cleared_restores(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    acs = off_acs()
    h = await boot(hass, hass_client_no_auth, freezer, acs, memory_value=record(50))
    await h.post(payload("test"))
    assert acs["climate.salon"].calls == []
    await h.post(payload("cleared", severity="warning"))
    assert acs["climate.salon"].settings()[0] == "cool"
    assert acs["climate.yatak"].settings()[0] == "dry"


async def test_restart_after_deadline_restores_now(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    """HA was down when the timeout passed (power cut): restore on boot."""
    acs = off_acs()
    await boot(hass, hass_client_no_auth, freezer, acs, memory_value=record(-120))
    assert acs["climate.salon"].settings()[:3] == ("cool", 22.5, "quiet")
    assert acs["climate.yatak"].settings()[:3] == ("dry", 25.0, "low")
    assert acs["climate.cocuk"].calls == []
    assert memory(hass) == ""


async def test_restart_respects_user_turned_on(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    acs = off_acs()
    acs["climate.yatak"] = FakeAC("yatak", HVACMode.HEAT, 27.0, "high")
    await boot(hass, hass_client_no_auth, freezer, acs, memory_value=record(-5))
    assert acs["climate.yatak"].calls == []
    assert acs["climate.salon"].settings()[0] == "cool"


async def test_restart_stale_memory_is_cleared_not_applied(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    acs = off_acs()
    await boot(hass, hass_client_no_auth, freezer, acs, memory_value=record(-3 * 24 * 60))
    assert all(ac.calls == [] for ac in acs.values())
    assert memory(hass) == ""


async def test_restart_without_memory_does_nothing(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    """No helper: it cannot know which ACs it turned off, so it leaves them."""
    acs = off_acs()
    h = await boot(hass, hass_client_no_auth, freezer, acs, memory_value=None)
    await h.advance(180)
    assert all(ac.calls == [] for ac in acs.values())


@pytest.mark.parametrize(
    "value",
    ["", "garbage", "d=abc;climate.salon=cool", "d=1;switch.x=on;light.y=on", "d=1"],
)
async def test_restart_ignores_empty_or_foreign_memory(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory, value: str
) -> None:
    """Only entries for this blueprint's own climates are ever acted on."""
    acs = off_acs()
    await boot(hass, hass_client_no_auth, freezer, acs, memory_value=value)
    assert all(ac.calls == [] for ac in acs.values())


async def test_restart_with_memory_and_timeout_disabled(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    """safety 0 writes d=0: after restart it waits for cleared (no deadline)."""
    acs = off_acs()
    h = await boot(
        hass,
        hass_client_no_auth,
        freezer,
        acs,
        memory_value="d=0;climate.salon=cool/22.5/quiet",
        safety_minutes=0,
    )
    await h.advance(600)
    assert acs["climate.salon"].calls == []
    await h.post(payload("cleared"))
    assert acs["climate.salon"].settings()[0] == "cool"
