"""Safety timeout and restore across restarts.

MOTTO: a missed `cleared` must never leave a shield (and therefore a device)
stuck. The timeout clears the key; a restart neither forgets an active key
nor keeps an expired one.
"""

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.stormguard.const import EVENT_EXPIRED

from .conftest import WEBHOOK_ID, entity_id, event, make_entry, setup_entry

URL = f"/api/webhook/{WEBHOOK_ID}"
ELECTRONICS = "binary_sensor.stormguard_electronics_shield"
CAR = "binary_sensor.stormguard_car_shield"
LAST_EVENT = "sensor.stormguard_last_event"


async def post(hass: HomeAssistant, client: Any, body: dict[str, Any]) -> None:
    resp = await client.post(URL, json=body)
    assert resp.status == 200
    await hass.async_block_till_done()


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.fixture
async def client(
    hass: HomeAssistant, hass_client_no_auth: Any, internal_url: str, freezer: FrozenDateTimeFactory
) -> Any:
    freezer.move_to("2026-10-17 10:00:00+00:00")
    await setup_entry(hass, make_entry(timeout=60))
    return await hass_client_no_auth()


async def test_timeout_clears_and_fires_expired(
    hass: HomeAssistant, client: Any, freezer: FrozenDateTimeFactory
) -> None:
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await post(hass, client, event("raised"))
    alert = hass.states.get(ELECTRONICS).attributes["active_alerts"][0]
    assert alert["expires_at"] == "2026-10-17T11:00:00+00:00"

    await advance(hass, freezer, 59)
    assert hass.states.get(ELECTRONICS).state == "on"
    assert expired == []

    await advance(hass, freezer, 2)
    state = hass.states.get(ELECTRONICS)
    assert state.state == "off"
    assert state.attributes["last_change_reason"] == "timeout"
    assert len(expired) == 1
    assert expired[0].data == {
        "entry_id": "sg_entry",
        "profile": "electronics",
        "type": "thunderstorm",
        "severity": "critical",
        "since": "2026-10-17T10:00:00+00:00",
        "reason": "timeout",
    }


async def test_timeout_is_per_key(
    hass: HomeAssistant, client: Any, freezer: FrozenDateTimeFactory
) -> None:
    await post(hass, client, event("raised", type="thunderstorm"))
    await advance(hass, freezer, 30)
    await post(hass, client, event("raised", type="wind", severity="warning"))
    await advance(hass, freezer, 31)  # first key expired, second still active
    state = hass.states.get(ELECTRONICS)
    assert state.state == "on"
    assert [a["type"] for a in state.attributes["active_alerts"]] == ["wind"]
    await advance(hass, freezer, 30)
    assert hass.states.get(ELECTRONICS).state == "off"


async def test_reraise_extends(
    hass: HomeAssistant, client: Any, freezer: FrozenDateTimeFactory
) -> None:
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await post(hass, client, event("raised"))
    await advance(hass, freezer, 50)
    await post(hass, client, event("raised"))
    await advance(hass, freezer, 50)  # 100 min after the first raised
    assert hass.states.get(ELECTRONICS).state == "on"
    assert expired == []
    await advance(hass, freezer, 11)
    assert hass.states.get(ELECTRONICS).state == "off"
    assert len(expired) == 1


async def test_cleared_cancels_timer(
    hass: HomeAssistant, client: Any, freezer: FrozenDateTimeFactory
) -> None:
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await post(hass, client, event("raised"))
    await post(hass, client, event("cleared"))
    await advance(hass, freezer, 120)
    assert expired == []
    assert hass.states.get(ELECTRONICS).attributes["last_change_reason"] == "cleared"


async def test_unload_cancels_timers(
    hass: HomeAssistant, client: Any, freezer: FrozenDateTimeFactory
) -> None:
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await post(hass, client, event("raised"))
    entry = hass.config_entries.async_entries("stormguard")[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await advance(hass, freezer, 120)
    assert expired == []


# -- restore ----------------------------------------------------------------------


def _alert(since: str, expires_at: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "thunderstorm",
        "severity": "critical",
        "headline": "Yıldırım riski",
        "since": since,
        "expires_at": expires_at,
        "occurred_at": since,
        **extra,
    }


async def _boot(hass: HomeAssistant, freezer: FrozenDateTimeFactory, states: list[State]) -> None:
    """Start hass as after a restart, with restored entity states."""
    freezer.move_to("2026-10-17 12:00:00+00:00")
    mock_restore_cache(hass, states)
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, make_entry(timeout=60))


async def test_restore_active_alert_rearms_remaining_time(
    hass: HomeAssistant, internal_url: str, freezer: FrozenDateTimeFactory
) -> None:
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await _boot(
        hass,
        freezer,
        [
            State(
                ELECTRONICS,
                "on",
                {
                    "active_alerts": [
                        _alert("2026-10-17T11:30:00+00:00", "2026-10-17T12:30:00+00:00")
                    ],
                    "last_change": "2026-10-17T11:30:00+00:00",
                    "last_change_reason": "raised",
                },
            ),
            State(
                LAST_EVENT,
                "2026-10-17T11:30:00+00:00",
                {"last_state": "raised", "profile": "electronics", "headline": "x"},
            ),
        ],
    )
    state = hass.states.get(ELECTRONICS)
    assert state.state == "on"
    assert state.attributes["active_alerts"][0]["since"] == "2026-10-17T11:30:00+00:00"
    last = hass.states.get(LAST_EVENT)
    assert last.state == "2026-10-17T11:30:00+00:00"
    assert last.attributes["last_state"] == "raised"

    await hass.async_start()
    await hass.async_block_till_done()
    await advance(hass, freezer, 29)
    assert hass.states.get(ELECTRONICS).state == "on"
    await advance(hass, freezer, 2)
    assert hass.states.get(ELECTRONICS).state == "off"
    assert len(expired) == 1


async def test_restore_expired_alert_clears_after_start(
    hass: HomeAssistant, internal_url: str, freezer: FrozenDateTimeFactory
) -> None:
    """Expired during downtime: on until HA has started, then off + expired event.

    Turning it off only after startup gives automations listening for
    `on → off` a chance to see the transition and restore the device.
    """
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await _boot(
        hass,
        freezer,
        [
            State(
                ELECTRONICS,
                "on",
                {
                    "active_alerts": [
                        _alert("2026-10-17T08:00:00+00:00", "2026-10-17T09:00:00+00:00")
                    ]
                },
            )
        ],
    )
    assert hass.states.get(ELECTRONICS).state == "on"
    assert expired == []

    await hass.async_start()
    await hass.async_block_till_done()
    await advance(hass, freezer, 0.05)  # RESTORE_GRACE
    state = hass.states.get(ELECTRONICS)
    assert state.state == "off"
    assert state.attributes["last_change_reason"] == "timeout"
    assert len(expired) == 1


async def test_restore_cleared_before_started_does_not_expire(
    hass: HomeAssistant, internal_url: str, freezer: FrozenDateTimeFactory, hass_client_no_auth: Any
) -> None:
    """A cleared arriving during startup wins over the pending restored timer."""
    expired = async_capture_events(hass, EVENT_EXPIRED)
    await _boot(
        hass,
        freezer,
        [
            State(
                ELECTRONICS,
                "on",
                {
                    "active_alerts": [
                        _alert("2026-10-17T08:00:00+00:00", "2026-10-17T09:00:00+00:00")
                    ]
                },
            )
        ],
    )
    client = await hass_client_no_auth()
    await post(hass, client, event("cleared"))
    assert hass.states.get(ELECTRONICS).state == "off"
    await hass.async_start()
    await advance(hass, freezer, 5)
    assert expired == []


async def test_restore_ignores_malformed(
    hass: HomeAssistant, internal_url: str, freezer: FrozenDateTimeFactory
) -> None:
    await _boot(
        hass,
        freezer,
        [
            State(
                ELECTRONICS,
                "on",
                {
                    "active_alerts": [
                        {"type": "snow", "severity": "critical"},
                        "garbage",
                        _alert("bad", "2026-10-17T12:30:00+00:00"),
                    ]
                },
            ),
            State(CAR, "on", {"active_alerts": "not-a-list"}),
            State(LAST_EVENT, "unknown", {}),
        ],
    )
    assert hass.states.get(ELECTRONICS).state == "off"
    assert hass.states.get(CAR).state == "off"
    assert hass.states.get(LAST_EVENT).state == "unknown"


async def test_entity_ids_are_stable(hass: HomeAssistant, client: Any) -> None:
    """The ids used by the user's automations (and this file) exist."""
    assert entity_id(hass, "electronics") == ELECTRONICS
    assert entity_id(hass, "car") == CAR
    assert entity_id(hass, "last_event") == LAST_EVENT


def test_dt_util_parses_app_format() -> None:
    """The app sends `toISOString()` (milliseconds + Z)."""
    parsed = dt_util.parse_datetime("2026-10-17T10:03:00.000Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
