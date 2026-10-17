"""Config flow, options flow and pairing link."""

import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from homeassistant import config_entries
from homeassistant.components.webhook import _HANDLERS
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers.network import NoURLAvailableError
import pytest

from custom_components.stormguard.const import (
    CONF_ALLOW_REMOTE,
    CONF_SAFETY_TIMEOUT,
    DOMAIN,
    WEBHOOK_ID_PATTERN,
)
from custom_components.stormguard.pairing import (
    app_accepts_base_url,
    app_accepts_remote_url,
    build_pairing_link,
    generate_webhook_id,
    is_private_host,
    normalize_base_url,
)

from .conftest import INTERNAL_URL, WEBHOOK_ID, make_entry, setup_entry

APP_ID_RE = re.compile(r"^stormguard_[A-Za-z0-9_-]{32}$")


async def _start(hass: HomeAssistant, allow_remote: bool = False) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ALLOW_REMOTE: allow_remote}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    return result


def _query(link: str) -> dict[str, list[str]]:
    parts = urlsplit(link)
    assert parts.scheme == "stormguardweather"
    assert parts.netloc == "home-assistant"
    return parse_qs(parts.query)


async def test_create_entry_local(hass: HomeAssistant, internal_url: str) -> None:
    """Happy path: generated id, pairing link, entry with default options."""
    result = await _start(hass)
    placeholders = result["description_placeholders"]
    webhook_id = placeholders["webhook_id"]

    assert APP_ID_RE.fullmatch(webhook_id)
    assert WEBHOOK_ID_PATTERN.fullmatch(webhook_id)
    assert placeholders["base_url"] == INTERNAL_URL
    assert placeholders["remote_url"] == "—"
    assert result["errors"] is None

    raw = placeholders["raw_link"]
    assert raw == (
        f"stormguardweather://home-assistant?url=http%3A%2F%2F192.168.1.50%3A8123&id={webhook_id}"
    )
    assert _query(raw) == {"url": [INTERNAL_URL], "id": [webhook_id]}
    assert placeholders["link"] == f"[StormGuard ↗]({raw})"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "StormGuard"
    assert result["data"] == {CONF_WEBHOOK_ID: webhook_id}
    assert result["options"] == {CONF_ALLOW_REMOTE: False, CONF_SAFETY_TIMEOUT: 120}

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == DOMAIN
    await hass.async_block_till_done()
    # The webhook is registered, local only, POST only.
    handler = hass.data[_HANDLERS][webhook_id]
    assert handler.local_only is True
    assert handler.allowed_methods == frozenset({"POST"})


async def test_trailing_slash_and_path_stripped(hass: HomeAssistant) -> None:
    """The link carries scheme://host:port only."""
    await async_process_ha_core_config(hass, {"internal_url": "http://homeassistant.local:8123/"})
    result = await _start(hass)
    assert result["description_placeholders"]["base_url"] == "http://homeassistant.local:8123"
    assert _query(result["description_placeholders"]["raw_link"])["url"] == [
        "http://homeassistant.local:8123"
    ]


async def test_create_entry_remote(hass: HomeAssistant, internal_url: str) -> None:
    """allow_remote: the https external URL is added as `remote`."""
    await async_process_ha_core_config(hass, {"external_url": "https://ev.example.com"})
    result = await _start(hass, allow_remote=True)
    placeholders = result["description_placeholders"]
    assert placeholders["remote_url"] == "https://ev.example.com"
    assert result["errors"] is None
    query = _query(placeholders["raw_link"])
    assert query["remote"] == ["https://ev.example.com"]
    assert "remote=https%3A%2F%2Fev.example.com" in placeholders["raw_link"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["options"][CONF_ALLOW_REMOTE] is True
    await hass.async_block_till_done()
    webhook_id = result["data"][CONF_WEBHOOK_ID]
    assert hass.data[_HANDLERS][webhook_id].local_only is False


async def test_remote_without_https_url_warns(hass: HomeAssistant, internal_url: str) -> None:
    """allow_remote without an https URL: warning, link without `remote`."""
    await async_process_ha_core_config(hass, {"external_url": "http://ev.example.com"})
    result = await _start(hass, allow_remote=True)
    assert result["errors"] == {"base": "no_remote_url"}
    assert "remote" not in _query(result["description_placeholders"]["raw_link"])


async def test_remote_url_not_added_when_local_only(hass: HomeAssistant, internal_url: str) -> None:
    """A local-only webhook would silently drop remote calls: no `remote`."""
    await async_process_ha_core_config(hass, {"external_url": "https://ev.example.com"})
    result = await _start(hass, allow_remote=False)
    assert "remote" not in _query(result["description_placeholders"]["raw_link"])


async def test_no_local_url(hass: HomeAssistant) -> None:
    """No URL at all: an error is shown, no link, entry can still be created."""
    with patch("custom_components.stormguard.pairing.get_url", side_effect=NoURLAvailableError):
        result = await _start(hass)
    assert result["errors"] == {"base": "no_local_url"}
    assert result["description_placeholders"]["raw_link"] == "—"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_insecure_local_url(hass: HomeAssistant) -> None:
    """Plain http on a public host is refused by the app: warn, no link."""
    await async_process_ha_core_config(hass, {"internal_url": "http://ev.example.com:8123"})
    result = await _start(hass)
    assert result["errors"] == {"base": "insecure_local_url"}
    assert result["description_placeholders"]["raw_link"] == "—"


async def test_single_instance(hass: HomeAssistant, internal_url: str) -> None:
    """A second setup aborts."""
    await setup_entry(hass, make_entry())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant, internal_url: str) -> None:
    """Options change the timeout and re-register the webhook."""
    entry = await setup_entry(hass, make_entry())
    assert hass.data[_HANDLERS][WEBHOOK_ID].local_only is True

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["description_placeholders"]["webhook_id"] == WEBHOOK_ID
    assert "url=http%3A%2F%2F192.168.1.50%3A8123" in result["description_placeholders"]["raw_link"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SAFETY_TIMEOUT: 30, CONF_ALLOW_REMOTE: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_SAFETY_TIMEOUT: 30, CONF_ALLOW_REMOTE: True}
    assert hass.data[_HANDLERS][WEBHOOK_ID].local_only is False
    assert entry.runtime_data.safety_timeout.total_seconds() == 30 * 60


@pytest.mark.parametrize("minutes", [5, 721])
async def test_options_flow_range(hass: HomeAssistant, internal_url: str, minutes: int) -> None:
    """Timeout must be within 10–720 minutes."""
    entry = await setup_entry(hass, make_entry())
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SAFETY_TIMEOUT: minutes, CONF_ALLOW_REMOTE: False}
        )


# -- pure helpers ---------------------------------------------------------------


def test_generate_webhook_id_unique_and_valid() -> None:
    ids = {generate_webhook_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(APP_ID_RE.fullmatch(i) and len(i) <= 64 for i in ids)


def test_build_pairing_link_encoding() -> None:
    link = build_pairing_link("http://[fd00::1]:8123", "abc_-1", "https://x.ui.nabu.casa")
    assert link == (
        "stormguardweather://home-assistant?url=http%3A%2F%2F%5Bfd00%3A%3A1%5D%3A8123"
        "&id=abc_-1&remote=https%3A%2F%2Fx.ui.nabu.casa"
    )
    assert "/" not in link.split("?", 1)[1]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://192.168.1.50:8123/", "http://192.168.1.50:8123"),
        ("http://ha.local:8123/some/path", "http://ha.local:8123"),
        ("https://ev.example.com", "https://ev.example.com"),
    ],
)
def test_normalize_base_url(url: str, expected: str) -> None:
    assert normalize_base_url(url) == expected


@pytest.mark.parametrize(
    ("host", "private"),
    [
        ("192.168.1.50", True),
        ("10.0.0.2", True),
        ("172.20.0.1", True),
        ("172.32.0.1", False),
        ("100.100.1.1", True),
        ("127.0.0.1", True),
        ("8.8.8.8", False),
        ("[fd00::1]", True),
        ("[fe80::1]", True),
        ("[2001:db8::1]", False),
        ("homeassistant", True),
        ("ha.local", True),
        ("box.tail1234.ts.net", True),
        ("ev.example.com", False),
    ],
)
def test_is_private_host_matches_app(host: str, private: bool) -> None:
    assert is_private_host(host) is private


@pytest.mark.parametrize(
    ("url", "base_ok", "remote_ok"),
    [
        ("http://192.168.1.50:8123", True, False),
        ("https://ev.example.com", True, True),
        ("http://ev.example.com", False, False),
        ("https://user@ev.example.com", False, False),
        ("ftp://192.168.1.50", False, False),
    ],
)
def test_app_acceptance(url: str, base_ok: bool, remote_ok: bool) -> None:
    assert app_accepts_base_url(url) is base_ok
    assert app_accepts_remote_url(url) is remote_ok
