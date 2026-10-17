"""Blueprint tests — schema validity and real behaviour in a running hass.

Every scenario posts the exact wire payload the app sends to
`/api/webhook/<id>` and asserts which device actions ran. The three
blueprints share one session algorithm, so most scenarios run against all
three (`KINDS`), which is what keeps the copies from drifting apart.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import shutil
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

BLUEPRINT_DIR = Path(__file__).parents[1] / "blueprints" / "automation" / "stormguard"
BLUEPRINTS = [
    "shield_actions.yaml",
    "switch_guard.yaml",
    "cover_guard.yaml",
    "climate_guard.yaml",
]
WEBHOOK_ID = "stormguard_TestWebhookId_123"
SOURCE_URL = "https://github.com/yasinozen35/stormguard-homeassistant/blob/main/blueprints/automation/stormguard/"


def payload(state: str = "raised", /, **overrides: Any) -> dict[str, Any]:
    """Return the app's wire payload (flat object)."""
    if state == "test":
        base: dict[str, Any] = {
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
        base = {
            "source": "stormguard",
            "version": 1,
            "state": state,
            "profile": "electronics",
            "type": "thunderstorm",
            "severity": "critical",
            "headline": "Yıldırım riski" if state == "raised" else "Risk geçti",
            "occurredAt": "2026-10-17T10:00:00.000Z",
        }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", BLUEPRINTS)
def test_blueprint_schema_valid(name: str) -> None:
    """Each blueprint passes Home Assistant's own automation blueprint schema."""
    path = BLUEPRINT_DIR / name
    data = load_yaml_dict(str(path))
    blueprint = Blueprint(
        data, path=str(path), expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA
    )
    meta = blueprint.metadata
    assert meta["source_url"] == SOURCE_URL + name
    assert meta["homeassistant"]["min_version"] == "2025.4.0"
    assert "webhook_id" in blueprint.inputs
    assert "local_only" in blueprint.inputs
    assert blueprint.inputs["profile"]["default"] in {"electronics", "car"}
    # Every blueprint ships a safety timeout with a non-zero default.
    assert blueprint.inputs["safety_minutes"]["default"] > 0
    assert blueprint.validate() is None


# ---------------------------------------------------------------------------
# Behaviour harness
# ---------------------------------------------------------------------------


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Use a temporary config dir so blueprints can be copied into it."""
    return hass_tmp_config_dir


@dataclass
class Kind:
    """How to drive and observe one blueprint."""

    file: str
    profile: str
    extra_inputs: Callable[[], dict[str, Any]]
    raised_service: tuple[str, str]
    restore_service: tuple[str, str]
    device_states: dict[str, str]
    protected_state: str


KINDS: dict[str, Kind] = {
    "shield_actions": Kind(
        file="shield_actions.yaml",
        profile="electronics",
        extra_inputs=lambda: {
            "raised_actions": [{"action": "test.raised"}],
            "cleared_actions": [{"action": "test.cleared"}],
        },
        raised_service=("test", "raised"),
        restore_service=("test", "cleared"),
        device_states={},
        protected_state="",
    ),
    "switch_guard": Kind(
        file="switch_guard.yaml",
        profile="electronics",
        extra_inputs=lambda: {"switches": ["switch.modem", "switch.tv"]},
        raised_service=("switch", "turn_off"),
        restore_service=("switch", "turn_on"),
        device_states={"switch.modem": "on", "switch.tv": "on"},
        protected_state="off",
    ),
    "cover_guard": Kind(
        file="cover_guard.yaml",
        profile="electronics",
        extra_inputs=lambda: {"covers": ["cover.garage"]},
        raised_service=("cover", "close_cover"),
        restore_service=("cover", "open_cover"),
        device_states={"cover.garage": "open"},
        protected_state="closed",
    ),
}


class Harness:
    """A running hass with one or more StormGuard blueprint automations."""

    def __init__(self, hass: HomeAssistant, client: Any, freezer: FrozenDateTimeFactory) -> None:
        self.hass = hass
        self.client = client
        self.freezer = freezer
        self.calls: dict[tuple[str, str], list[ServiceCall]] = {}

    def mock(self, domain: str, service: str) -> list[ServiceCall]:
        key = (domain, service)
        if key not in self.calls:
            self.calls[key] = async_mock_service(self.hass, domain, service)
        return self.calls[key]

    async def post(
        self, body: Any, *, raw: str | None = None, content_type: str | None = None
    ) -> int:
        if raw is not None:
            resp = await self.client.post(
                f"/api/webhook/{WEBHOOK_ID}",
                data=raw,
                headers={"Content-Type": content_type or "application/json"},
            )
        else:
            resp = await self.client.post(f"/api/webhook/{WEBHOOK_ID}", json=body)
        await settle()
        return resp.status

    async def advance(self, minutes: float) -> None:
        self.freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(self.hass)
        await settle()


async def settle(rounds: int = 100) -> None:
    """Let pending script steps run.

    `hass.async_block_till_done()` cannot be used here: a blueprint session
    is a long-running automation run (it waits for `cleared`), and
    block_till_done would wait for it to finish.
    """
    for _ in range(rounds):
        await asyncio.sleep(0)


def copy_blueprints(hass: HomeAssistant) -> None:
    dest = Path(hass.config.path("blueprints", "automation", "stormguard"))
    dest.mkdir(parents=True, exist_ok=True)
    for name in BLUEPRINTS:
        shutil.copy(BLUEPRINT_DIR / name, dest / name)


def automation_config(kind: Kind, alias: str = "sg", **inputs: Any) -> dict[str, Any]:
    return {
        "id": alias,
        "alias": alias,
        "use_blueprint": {
            "path": f"stormguard/{kind.file}",
            "input": {
                "webhook_id": WEBHOOK_ID,
                "profile": kind.profile,
                "safety_minutes": 60,
                **kind.extra_inputs(),
                **inputs,
            },
        },
    }


async def setup_automations(hass: HomeAssistant, *configs: dict[str, Any]) -> None:
    copy_blueprints(hass)
    assert await async_setup_component(hass, "automation", {"automation": list(configs)})
    await hass.async_block_till_done()
    for config in configs:
        state = hass.states.get(f"automation.{config['alias']}")
        assert state is not None, "automation was not created (invalid blueprint config?)"
        assert state.state == "on", state


@pytest.fixture
async def make(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> Callable[..., Any]:
    """Create a harness with one automation of the given kind."""
    freezer.move_to("2026-10-17 10:00:00+00:00")
    assert await async_setup_component(hass, "webhook", {})

    async def _make(kind_name: str, **inputs: Any) -> tuple[Harness, Kind]:
        kind = KINDS[kind_name]
        for entity_id, state in kind.device_states.items():
            hass.states.async_set(entity_id, state)
        harness = Harness(hass, await hass_client_no_auth(), freezer)
        harness.mock(*kind.raised_service)
        harness.mock(*kind.restore_service)
        await setup_automations(hass, automation_config(kind, **inputs))
        return harness, kind

    return _make


def counts(h: Harness, kind: Kind) -> tuple[int, int]:
    return len(h.calls[kind.raised_service]), len(h.calls[kind.restore_service])


def simulate_device(h: Harness, kind: Kind) -> None:
    """Make mocked services change device state like a real device would."""
    if not kind.device_states:
        return
    for entity_id in kind.device_states:
        h.hass.states.async_set(entity_id, kind.protected_state)


ALL = list(KINDS)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind_name", ALL)
async def test_raised_then_cleared(make: Callable[..., Any], kind_name: str) -> None:
    """raised → protect; cleared → restore exactly once."""
    h, kind = await make(kind_name)

    assert await h.post(payload("raised")) == 200
    assert counts(h, kind) == (1, 0)

    await h.advance(5)
    assert await h.post(payload("cleared")) == 200
    assert counts(h, kind) == (1, 1)

    # Nothing else happens afterwards (no second restore at the old deadline).
    await h.advance(120)
    assert counts(h, kind) == (1, 1)


async def test_switch_guard_targets(make: Callable[..., Any]) -> None:
    """Only switches that were on are turned back on."""
    h, kind = await make("switch_guard")
    h.hass.states.async_set("switch.tv", "off")  # user had the TV off already

    await h.post(payload("raised"))
    off = h.calls[kind.raised_service][0]
    assert sorted(off.data["entity_id"]) == ["switch.modem", "switch.tv"]

    await h.post(payload("cleared"))
    on = h.calls[kind.restore_service][0]
    assert on.data["entity_id"] == ["switch.modem"]


async def test_cover_guard_targets_and_reopen(make: Callable[..., Any]) -> None:
    """The cover is closed on raised and reopened on cleared."""
    h, kind = await make("cover_guard", profile="car")
    await h.post(payload("raised", profile="car", type="hail"))
    assert h.calls[kind.raised_service][0].data["entity_id"] == ["cover.garage"]
    await h.post(payload("cleared", profile="car", type="hail"))
    assert h.calls[kind.restore_service][0].data["entity_id"] == ["cover.garage"]


async def test_cover_guard_no_reopen(make: Callable[..., Any]) -> None:
    """With reopen off the cover is closed but never opened."""
    h, kind = await make("cover_guard", reopen=False)
    await h.post(payload("raised"))
    await h.post(payload("cleared"))
    await h.advance(120)
    assert counts(h, kind) == (1, 0)


async def test_cover_already_closed_not_opened(make: Callable[..., Any]) -> None:
    """A cover that was already closed before the storm stays closed."""
    h, kind = await make("cover_guard")
    h.hass.states.async_set("cover.garage", "closed")
    await h.post(payload("raised"))
    await h.post(payload("cleared"))
    assert counts(h, kind) == (1, 0)


@pytest.mark.parametrize("kind_name", ALL)
async def test_safety_timeout_restores(make: Callable[..., Any], kind_name: str) -> None:
    """No cleared → restore after the safety timeout, not before."""
    h, kind = await make(kind_name, safety_minutes=30)
    await h.post(payload("raised"))

    await h.advance(29)
    assert counts(h, kind) == (1, 0)

    await h.advance(2)
    assert counts(h, kind) == (1, 1)

    # A late cleared after the timeout does nothing.
    await h.post(payload("cleared"))
    assert counts(h, kind) == (1, 1)


@pytest.mark.parametrize("kind_name", ALL)
async def test_reraise_extends_timeout(make: Callable[..., Any], kind_name: str) -> None:
    """A new raised for the shield during the session extends the deadline."""
    h, kind = await make(kind_name, safety_minutes=30)
    await h.post(payload("raised", severity="warning"))
    await h.advance(20)
    await h.post(payload("raised", severity="critical"))
    await h.advance(20)  # 40 min after the first raised, 20 after the second
    assert counts(h, kind) == (1, 0)
    await h.advance(11)
    assert counts(h, kind) == (1, 1)


@pytest.mark.parametrize("kind_name", ALL)
async def test_escalation_does_not_restore_early(make: Callable[..., Any], kind_name: str) -> None:
    """warning → critical: the app sends raised(critical) then cleared(warning).

    The cleared for the old key must not restore the device while the new key
    is still active.
    """
    h, kind = await make(kind_name)
    await h.post(payload("raised", severity="warning"))
    await h.advance(10)
    await h.post(payload("raised", severity="critical"))
    await h.post(payload("cleared", severity="warning"))
    assert counts(h, kind) == (1, 0)

    await h.post(payload("cleared", severity="critical"))
    assert counts(h, kind) == (1, 1)


@pytest.mark.parametrize("kind_name", ALL)
async def test_two_keys_same_profile(make: Callable[..., Any], kind_name: str) -> None:
    """Two keys active (thunderstorm + wind): restore only after both clear."""
    h, kind = await make(kind_name)
    await h.post(payload("raised", type="thunderstorm"))
    await h.post(payload("raised", type="wind", severity="warning"))
    await h.post(payload("cleared", type="thunderstorm"))
    assert counts(h, kind) == (1, 0)
    await h.post(payload("cleared", type="wind", severity="warning"))
    assert counts(h, kind) == (1, 1)


@pytest.mark.parametrize("kind_name", ALL)
async def test_test_event_does_nothing(make: Callable[..., Any], kind_name: str) -> None:
    """The app's test button never changes a device — idle or mid-session."""
    h, kind = await make(kind_name)
    assert await h.post(payload("test")) == 200
    assert counts(h, kind) == (0, 0)

    await h.post(payload("raised"))
    await h.post(payload("test"))
    assert counts(h, kind) == (1, 0)


@pytest.mark.parametrize("kind_name", ALL)
async def test_other_profile_does_nothing(make: Callable[..., Any], kind_name: str) -> None:
    """Events for another shield are ignored, idle or mid-session."""
    h, kind = await make(kind_name)
    await h.post(payload("raised", profile="car", type="hail"))
    assert counts(h, kind) == (0, 0)

    await h.post(payload("raised"))
    await h.post(payload("cleared", profile="car", type="thunderstorm"))
    assert counts(h, kind) == (1, 0)


@pytest.mark.parametrize("kind_name", ALL)
async def test_below_min_severity_does_nothing(make: Callable[..., Any], kind_name: str) -> None:
    """min=critical: warning raised/cleared are ignored."""
    h, kind = await make(kind_name, min_severity="critical")
    await h.post(payload("raised", severity="warning"))
    assert counts(h, kind) == (0, 0)

    await h.post(payload("raised", severity="critical"))
    # cleared(warning) is below the minimum → ignored, does not end the session
    await h.post(payload("cleared", severity="warning"))
    assert counts(h, kind) == (1, 0)
    await h.post(payload("cleared", severity="critical"))
    assert counts(h, kind) == (1, 1)


async def test_type_filter(make: Callable[..., Any]) -> None:
    """An alert type outside the filter does nothing."""
    h, kind = await make("shield_actions", alert_types=["thunderstorm"])
    await h.post(payload("raised", type="wind"))
    assert counts(h, kind) == (0, 0)
    await h.post(payload("raised", type="thunderstorm"))
    assert counts(h, kind) == (1, 0)


@pytest.mark.parametrize(
    "body",
    [
        payload("raised", source="other"),
        payload("RAISED"),
        payload("unknown_future_state"),
        payload("raised", severity="info"),
        payload("raised", profile=None),
        ["not", "an", "object"],
    ],
    ids=["wrong-source", "case", "unknown-state", "info", "no-profile", "list"],
)
async def test_foreign_payloads_ignored(make: Callable[..., Any], body: Any) -> None:
    """Anything that is not a valid StormGuard raised event is ignored."""
    h, kind = await make("switch_guard")
    assert await h.post(body) == 200
    assert counts(h, kind) == (0, 0)


async def test_non_json_body_ignored(make: Callable[..., Any]) -> None:
    """Form-encoded or broken bodies do not crash the automation."""
    h, kind = await make("switch_guard")
    await h.post(
        None,
        raw="state=raised&profile=electronics",
        content_type="application/x-www-form-urlencoded",
    )
    await h.post(None, raw="{broken", content_type="text/plain")
    assert counts(h, kind) == (0, 0)


async def test_future_fields_and_version_accepted(make: Callable[..., Any]) -> None:
    """Unknown fields are ignored and version 2 still works."""
    h, kind = await make("switch_guard")
    await h.post(payload("raised", version=2, newField={"x": 1}))
    assert counts(h, kind) == (1, 0)


async def test_get_is_rejected(make: Callable[..., Any]) -> None:
    """Only POST triggers the automation."""
    h, kind = await make("switch_guard")
    resp = await h.client.get(f"/api/webhook/{WEBHOOK_ID}")
    await settle()
    assert resp.status == 405
    assert counts(h, kind) == (0, 0)


async def test_failing_raised_action_still_restores(make: Callable[..., Any]) -> None:
    """A raised action that errors must not cancel the restore."""
    h, kind = await make(
        "shield_actions",
        raised_actions=[{"action": "test.boom"}, {"action": "test.raised"}],
    )

    def _boom(call: ServiceCall) -> None:
        raise HomeAssistantError("device offline")

    h.hass.services.async_register("test", "boom", _boom)
    await h.post(payload("raised"))
    await h.post(payload("cleared"))
    assert counts(h, kind) == (0, 1)


async def test_two_blueprints_share_one_webhook_id(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    """The app has ONE webhook id: several blueprint instances must share it."""
    freezer.move_to("2026-10-17 10:00:00+00:00")
    assert await async_setup_component(hass, "webhook", {})
    hass.states.async_set("switch.modem", "on")
    hass.states.async_set("cover.garage", "open")
    h = Harness(hass, await hass_client_no_auth(), freezer)
    off = h.mock("switch", "turn_off")
    on = h.mock("switch", "turn_on")
    close = h.mock("cover", "close_cover")
    opened = h.mock("cover", "open_cover")
    await setup_automations(
        hass,
        automation_config(KINDS["switch_guard"], alias="modem", switches=["switch.modem"]),
        automation_config(
            KINDS["cover_guard"], alias="garage", profile="car", covers=["cover.garage"]
        ),
    )

    await h.post(payload("raised"))  # electronics
    assert (len(off), len(close)) == (1, 0)
    await h.post(payload("raised", profile="car", type="hail"))
    assert (len(off), len(close)) == (1, 1)
    await h.post(payload("cleared"))
    assert (len(on), len(opened)) == (1, 0)
    await h.post(payload("cleared", profile="car", type="hail"))
    assert (len(on), len(opened)) == (1, 1)


# ---------------------------------------------------------------------------
# Home Assistant restart
# ---------------------------------------------------------------------------


async def start_with_restored_automation(
    hass: HomeAssistant,
    client_factory: Any,
    freezer: FrozenDateTimeFactory,
    kind: Kind,
    *,
    last_triggered_minutes_ago: float,
    device_state: str | None,
    **inputs: Any,
) -> Harness:
    """Boot hass as if it restarted while an automation session was running."""
    now = dt_util.parse_datetime("2026-10-17 12:00:00+00:00")
    freezer.move_to(now)
    last = now - timedelta(minutes=last_triggered_minutes_ago)
    mock_restore_cache(
        hass,
        [State("automation.sg", "on", {"last_triggered": last.isoformat()})],
    )
    hass.set_state(CoreState.not_running)
    assert await async_setup_component(hass, "webhook", {})
    if device_state is not None:
        for entity_id in kind.device_states:
            hass.states.async_set(entity_id, device_state)
    h = Harness(hass, None, freezer)
    h.mock(*kind.raised_service)
    h.mock(*kind.restore_service)
    copy_blueprints(hass)
    assert await async_setup_component(
        hass, "automation", {"automation": [automation_config(kind, **inputs)]}
    )
    await hass.async_start()
    await settle()
    h.client = await client_factory()
    return h


GUARDS = ["switch_guard", "cover_guard"]


@pytest.mark.parametrize("kind_name", GUARDS)
async def test_restart_mid_session_resumes_remaining_time(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory, kind_name: str
) -> None:
    """Restart 10 min into a 60 min session: restore 50 min later."""
    kind = KINDS[kind_name]
    h = await start_with_restored_automation(
        hass,
        hass_client_no_auth,
        freezer,
        kind,
        last_triggered_minutes_ago=10,
        device_state=kind.protected_state,
    )
    assert counts(h, kind) == (0, 0)
    await h.advance(49)
    assert counts(h, kind) == (0, 0)
    await h.advance(2)
    assert counts(h, kind) == (0, 1)


@pytest.mark.parametrize("kind_name", ALL)
async def test_restart_mid_session_cleared_restores(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory, kind_name: str
) -> None:
    """After a restart, any cleared for the shield ends the resumed session."""
    kind = KINDS[kind_name]
    h = await start_with_restored_automation(
        hass,
        hass_client_no_auth,
        freezer,
        kind,
        last_triggered_minutes_ago=10,
        device_state=kind.protected_state or None,
    )
    await h.post(payload("test"))
    assert counts(h, kind) == (0, 0)
    await h.post(payload("cleared", severity="warning"))
    assert counts(h, kind) == (0, 1)


@pytest.mark.parametrize("kind_name", GUARDS)
async def test_restart_after_deadline_restores_now(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory, kind_name: str
) -> None:
    """HA was down when the timeout passed (power cut): restore on boot."""
    kind = KINDS[kind_name]
    h = await start_with_restored_automation(
        hass,
        hass_client_no_auth,
        freezer,
        kind,
        last_triggered_minutes_ago=180,
        device_state=kind.protected_state,
    )
    assert counts(h, kind) == (0, 1)


@pytest.mark.parametrize("kind_name", GUARDS)
async def test_restart_device_not_protected_does_nothing(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory, kind_name: str
) -> None:
    """Device already in its normal state: a restart changes nothing."""
    kind = KINDS[kind_name]
    h = await start_with_restored_automation(
        hass,
        hass_client_no_auth,
        freezer,
        kind,
        last_triggered_minutes_ago=10,
        device_state=next(iter(kind.device_states.values())),
    )
    await h.advance(120)
    assert counts(h, kind) == (0, 0)


@pytest.mark.parametrize("kind_name", GUARDS)
async def test_restart_long_ago_does_nothing(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory, kind_name: str
) -> None:
    """Last session days ago: a device the user switched off stays off."""
    kind = KINDS[kind_name]
    h = await start_with_restored_automation(
        hass,
        hass_client_no_auth,
        freezer,
        kind,
        last_triggered_minutes_ago=3 * 24 * 60,
        device_state=kind.protected_state,
    )
    await h.advance(120)
    assert counts(h, kind) == (0, 0)


async def test_restart_resumed_session_then_raised_extends(
    hass: HomeAssistant, hass_client_no_auth: Any, freezer: FrozenDateTimeFactory
) -> None:
    """A raised after restart is tracked; restore waits for its cleared."""
    kind = KINDS["switch_guard"]
    h = await start_with_restored_automation(
        hass,
        hass_client_no_auth,
        freezer,
        kind,
        last_triggered_minutes_ago=10,
        device_state="off",
    )
    await h.post(payload("raised"))
    await h.post(payload("cleared", severity="warning"))  # ends the unknown '*' key only
    assert counts(h, kind) == (0, 0)
    await h.post(payload("cleared"))
    assert counts(h, kind) == (0, 1)


async def test_shield_actions_with_default_inputs(make: Callable[..., Any]) -> None:
    """Empty action lists (the defaults) are valid and the session still ends."""
    h, _kind = await make("shield_actions", raised_actions=[], cleared_actions=[])
    assert await h.post(payload("raised")) == 200
    assert await h.post(payload("cleared")) == 200
    state = h.hass.states.get("automation.sg")
    assert state.state == "on"
    assert state.attributes["current"] == 0
