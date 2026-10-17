"""Webhook handling: validation, shield state, bus events, unload."""

from typing import Any
from unittest.mock import patch

from homeassistant.components.webhook import _HANDLERS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.stormguard.const import EVENT_STORMGUARD, PROFILES
from custom_components.stormguard.payload import InvalidPayload, parse_event

from .conftest import WEBHOOK_ID, entity_id, event, make_entry, setup_entry

URL = f"/api/webhook/{WEBHOOK_ID}"


@pytest.fixture
async def client(hass: HomeAssistant, hass_client_no_auth: Any, internal_url: str) -> Any:
    await setup_entry(hass, make_entry())
    return await hass_client_no_auth()


async def post(hass: HomeAssistant, client: Any, body: Any = None, **kwargs: Any) -> int:
    if body is not None:
        kwargs["json"] = body
    resp = await client.post(URL, **kwargs)
    await hass.async_block_till_done()
    return resp.status


def shield(hass: HomeAssistant, profile: str = "electronics") -> Any:
    state = hass.states.get(entity_id(hass, profile))
    assert state is not None
    return state


def snapshot(hass: HomeAssistant) -> dict[str, Any]:
    out = {}
    for key in (*PROFILES, "last_event"):
        state = hass.states.get(entity_id(hass, key))
        out[key] = (state.state, dict(state.attributes))
    return out


async def test_entities_created(hass: HomeAssistant, client: Any) -> None:
    """Four shield binary sensors (off, device_class safety) + last event."""
    for profile in PROFILES:
        state = shield(hass, profile)
        assert state.state == "off"
        assert state.attributes["device_class"] == "safety"
        assert state.attributes["active_alerts"] == []
    assert hass.states.get(entity_id(hass, "last_event")).state == "unknown"
    assert entity_id(hass, "electronics") == "binary_sensor.stormguard_electronics_shield"


async def test_raised_turns_on(hass: HomeAssistant, client: Any) -> None:
    events = async_capture_events(hass, EVENT_STORMGUARD)
    assert await post(hass, client, event("raised")) == 200

    state = shield(hass)
    assert state.state == "on"
    alerts = state.attributes["active_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "thunderstorm"
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["headline"] == "Yıldırım riski"
    assert alerts[0]["since"]
    assert state.attributes["last_change_reason"] == "raised"
    assert state.attributes["last_change"]
    # Other shields untouched.
    assert shield(hass, "car").state == "off"

    assert len(events) == 1
    data = events[0].data
    assert data["entry_id"] == "sg_entry"
    assert data["state"] == "raised"
    assert data["profile"] == "electronics"
    assert data["source"] == "stormguard"

    last = hass.states.get(entity_id(hass, "last_event"))
    assert last.state != "unknown"
    assert last.attributes["last_state"] == "raised"


async def test_two_keys_and_clears(hass: HomeAssistant, client: Any) -> None:
    """On while ANY key is active; cleared removes only its key."""
    await post(hass, client, event("raised", type="thunderstorm", severity="critical"))
    await post(hass, client, event("raised", type="wind", severity="warning"))
    assert len(shield(hass).attributes["active_alerts"]) == 2

    await post(hass, client, event("cleared", type="thunderstorm", severity="critical"))
    state = shield(hass)
    assert state.state == "on"
    assert [a["type"] for a in state.attributes["active_alerts"]] == ["wind"]
    assert state.attributes["last_change_reason"] == "cleared"

    await post(hass, client, event("cleared", type="wind", severity="warning"))
    assert shield(hass).state == "off"


async def test_escalation_keeps_shield_on(hass: HomeAssistant, client: Any) -> None:
    """warning → critical is sent as raised(critical) + cleared(warning)."""
    await post(hass, client, event("raised", severity="warning"))
    await post(hass, client, event("raised", severity="critical"))
    await post(hass, client, event("cleared", severity="warning"))
    state = shield(hass)
    assert state.state == "on"
    assert [a["severity"] for a in state.attributes["active_alerts"]] == ["critical"]


async def test_reraise_same_key_keeps_since(hass: HomeAssistant, client: Any) -> None:
    await post(hass, client, event("raised", headline="first"))
    since = shield(hass).attributes["active_alerts"][0]["since"]
    await post(hass, client, event("raised", headline="second"))
    alerts = shield(hass).attributes["active_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["since"] == since
    assert alerts[0]["headline"] == "second"


async def test_cleared_unknown_key_is_harmless(hass: HomeAssistant, client: Any) -> None:
    events = async_capture_events(hass, EVENT_STORMGUARD)
    assert await post(hass, client, event("cleared")) == 200
    assert shield(hass).state == "off"
    assert shield(hass).attributes["last_change_reason"] is None
    assert len(events) == 1  # still published on the bus


async def test_test_event_changes_no_shield(hass: HomeAssistant, client: Any) -> None:
    """test: updates last event + bus, never a shield (idle or active)."""
    await post(hass, client, event("raised"))
    before = snapshot(hass)
    events = async_capture_events(hass, EVENT_STORMGUARD)

    assert await post(hass, client, event("test")) == 200
    after = snapshot(hass)
    for profile in PROFILES:
        assert after[profile] == before[profile]
    assert after["last_event"][1]["last_state"] == "test"
    assert after["last_event"][1]["headline"] == "StormGuard test"
    assert len(events) == 1
    assert events[0].data["state"] == "test"
    assert events[0].data["profile"] is None


async def test_test_event_with_profile_fields_still_changes_nothing(
    hass: HomeAssistant, client: Any
) -> None:
    await post(hass, client, event("test", profile="electronics", type="thunderstorm"))
    assert shield(hass).state == "off"


INVALID: list[tuple[str, dict[str, Any]]] = [
    ("wrong-source", {"source": "other"}),
    ("no-source", {"source": None}),
    ("version-0", {"version": 0}),
    ("version-str", {"version": "1"}),
    ("version-bool", {"version": True}),
    ("no-state", {"state": None}),
    ("state-number", {"state": 3}),
    ("bad-profile", {"profile": "garage"}),
    ("no-profile", {"profile": None}),
    ("bad-type", {"type": "snow"}),
    ("info-severity", {"severity": "info"}),
    ("no-severity", {"severity": None}),
    ("headline-number", {"headline": 42}),
    ("no-occurred", {"occurredAt": None}),
    ("bad-occurred", {"occurredAt": "yesterday"}),
]


@pytest.mark.parametrize(("name", "change"), INVALID, ids=[n for n, _ in INVALID])
async def test_invalid_payload_400(
    hass: HomeAssistant, client: Any, name: str, change: dict[str, Any]
) -> None:
    await post(hass, client, event("raised"))  # an active shield must survive
    before = snapshot(hass)
    events = async_capture_events(hass, EVENT_STORMGUARD)

    assert await post(hass, client, event("raised", **change)) == 400
    assert await post(hass, client, event("cleared", **change)) == 400
    assert snapshot(hass) == before
    assert events == []


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        ("{not json", "application/json"),
        ("[1, 2]", "application/json"),
        ('"raised"', "application/json"),
        ("", "application/json"),
        ("state=raised", "application/x-www-form-urlencoded"),
    ],
)
async def test_bad_bodies_400(
    hass: HomeAssistant, client: Any, data: str, content_type: str
) -> None:
    before = snapshot(hass)
    status = await post(hass, client, data=data, headers={"Content-Type": content_type})
    assert status == 400
    assert snapshot(hass) == before


async def test_body_too_large_400(hass: HomeAssistant, client: Any) -> None:
    body = event("raised", padding="x" * 20000)
    assert await post(hass, client, body) == 400
    assert shield(hass).state == "off"


async def test_test_event_invalid_source_400(hass: HomeAssistant, client: Any) -> None:
    assert await post(hass, client, event("test", source="nope")) == 400


async def test_unknown_state_ignored(hass: HomeAssistant, client: Any) -> None:
    events = async_capture_events(hass, EVENT_STORMGUARD)
    before = snapshot(hass)
    assert await post(hass, client, event("snoozed")) == 200
    assert snapshot(hass) == before
    assert events == []


async def test_future_fields_and_version(hass: HomeAssistant, client: Any) -> None:
    body = event("raised", version=2, confidence=0.8, nested={"a": [1]})
    assert await post(hass, client, body) == 200
    assert shield(hass).state == "on"


async def test_headline_truncated(hass: HomeAssistant, client: Any) -> None:
    await post(hass, client, event("raised", headline="ç" * 900))
    assert len(shield(hass).attributes["active_alerts"][0]["headline"]) == 500


async def test_occurred_at_without_timezone(hass: HomeAssistant, client: Any) -> None:
    assert await post(hass, client, event("raised", occurredAt="2026-10-17T10:00:00")) == 200
    assert shield(hass).state == "on"


@pytest.mark.parametrize("method", ["get", "put"])
async def test_wrong_method(hass: HomeAssistant, client: Any, method: str) -> None:
    resp = await getattr(client, method)(URL, json=event("raised"))
    await hass.async_block_till_done()
    assert resp.status == 405
    assert shield(hass).state == "off"


async def test_remote_request_dropped_when_local_only(hass: HomeAssistant, client: Any) -> None:
    """Default: requests from outside the home network never change state."""
    with patch("homeassistant.components.webhook.is_cloud_connection", return_value=True):
        assert await post(hass, client, event("raised")) == 200
    assert shield(hass).state == "off"


async def test_remote_request_accepted_when_allowed(
    hass: HomeAssistant, hass_client_no_auth: Any, internal_url: str
) -> None:
    await setup_entry(hass, make_entry(allow_remote=True))
    client = await hass_client_no_auth()
    with patch("homeassistant.components.webhook.is_cloud_connection", return_value=True):
        assert await post(hass, client, event("raised")) == 200
    assert shield(hass).state == "on"


async def test_webhook_id_never_logged(
    hass: HomeAssistant, client: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG", logger="custom_components.stormguard")
    await post(hass, client, event("raised"))
    await post(hass, client, event("raised", source="x"))
    await post(hass, client, data="{", headers={"Content-Type": "application/json"})
    ours = [r for r in caplog.records if r.name.startswith("custom_components.stormguard")]
    assert ours, "expected debug logs from the integration"
    assert all(WEBHOOK_ID not in r.getMessage() for r in ours)
    assert all("Yıldırım" not in r.getMessage() for r in ours if r.levelname != "DEBUG")


async def test_unload_unregisters_webhook(hass: HomeAssistant, client: Any) -> None:
    entry = hass.config_entries.async_entries("stormguard")[0]
    assert WEBHOOK_ID in hass.data[_HANDLERS]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert WEBHOOK_ID not in hass.data[_HANDLERS]

    # HA answers 200 for unknown webhooks (it never reveals which exist).
    assert await post(hass, client, event("raised")) == 200


async def test_reload_reregisters_and_keeps_state(hass: HomeAssistant, client: Any) -> None:
    await post(hass, client, event("raised"))
    entry = hass.config_entries.async_entries("stormguard")[0]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert WEBHOOK_ID in hass.data[_HANDLERS]
    assert shield(hass).state == "on"

    await post(hass, client, event("cleared"))
    assert shield(hass).state == "off"


async def test_webhook_in_use_fails_setup(hass: HomeAssistant, internal_url: str) -> None:
    """If an automation already owns the id, setup errors instead of stealing it."""
    from homeassistant.components import webhook  # noqa: PLC0415
    from homeassistant.setup import async_setup_component  # noqa: PLC0415

    assert await async_setup_component(hass, "webhook", {})

    async def _other(*_: Any) -> None:
        return None

    webhook.async_register(hass, "automation", "other", WEBHOOK_ID, _other)
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.data[_HANDLERS][WEBHOOK_ID].domain == "automation"


# -- payload unit tests -----------------------------------------------------------


def test_parse_event_ok() -> None:
    parsed = parse_event(event("raised"))
    assert parsed is not None
    assert parsed.key == "thunderstorm|critical"
    assert parsed.as_event_data()["occurredAt"].startswith("2026-10-17T10:00:00")


def test_parse_test_event_drops_fields() -> None:
    parsed = parse_event(event("test", profile="car"))
    assert parsed is not None
    assert (parsed.profile, parsed.type, parsed.severity) == (None, None, None)


def test_parse_unknown_state_is_none() -> None:
    assert parse_event(event("later")) is None


@pytest.mark.parametrize(("name", "change"), INVALID, ids=[n for n, _ in INVALID])
def test_parse_event_invalid(name: str, change: dict[str, Any]) -> None:
    with pytest.raises(InvalidPayload):
        parse_event(event("raised", **change))
