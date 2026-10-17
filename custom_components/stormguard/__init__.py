"""StormGuard — receive StormGuard app events through a webhook.

MOTTO: *the app publishes events, Home Assistant manages device state.*
This integration turns the app's `raised` / `cleared` facts into four
binary sensors (one per shield) with a safety timeout; your automations decide
what devices do. It never stores device state and knows no entity ids.
"""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from http import HTTPStatus
import logging

from aiohttp import web
from aiohttp.hdrs import METH_POST
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.util.json import json_loads

from .const import (
    CONF_ALLOW_REMOTE,
    CONF_SAFETY_TIMEOUT,
    DEFAULT_ALLOW_REMOTE,
    DEFAULT_SAFETY_TIMEOUT,
    DOMAIN,
    MAX_BODY_BYTES,
    NAME,
)
from .payload import InvalidPayload, parse_event
from .tracker import ShieldTracker

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type StormGuardConfigEntry = ConfigEntry[ShieldTracker]


async def async_setup_entry(hass: HomeAssistant, entry: StormGuardConfigEntry) -> bool:
    """Set up StormGuard from a config entry."""
    minutes = int(entry.options.get(CONF_SAFETY_TIMEOUT, DEFAULT_SAFETY_TIMEOUT))
    tracker = ShieldTracker(hass, entry.entry_id, timedelta(minutes=minutes))
    entry.runtime_data = tracker
    entry.async_on_unload(tracker.async_shutdown)

    # Entities first: they restore the previous state (and timers) before the
    # first event can arrive.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    webhook_id: str = entry.data[CONF_WEBHOOK_ID]
    allow_remote = bool(entry.options.get(CONF_ALLOW_REMOTE, DEFAULT_ALLOW_REMOTE))
    try:
        webhook.async_register(
            hass,
            DOMAIN,
            NAME,
            webhook_id,
            partial(_async_handle_webhook, tracker),
            local_only=not allow_remote,
            allowed_methods=[METH_POST],
        )
    except ValueError as err:
        # Another handler (e.g. a blueprint automation) already owns this id.
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="webhook_in_use") from err
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StormGuardConfigEntry) -> bool:
    """Unload a config entry (the webhook is unregistered by async_on_unload)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: StormGuardConfigEntry) -> None:
    """Re-register the webhook with the new options."""
    await hass.config_entries.async_reload(entry.entry_id)


def _bad_request(reason: str) -> web.Response:
    # The webhook id is never logged (it is a secret); neither is the body.
    _LOGGER.debug("Rejected StormGuard webhook call: %s", reason)
    return web.Response(status=HTTPStatus.BAD_REQUEST, text=reason)


async def _async_handle_webhook(
    tracker: ShieldTracker, hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response | None:
    """Validate one POST and apply it."""
    raw = await request.content.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        return _bad_request("body too large")
    try:
        body = json_loads(raw)
    except ValueError:
        return _bad_request("body is not valid JSON")

    try:
        event = parse_event(body)
    except InvalidPayload as err:
        return _bad_request(str(err))

    if event is None:
        _LOGGER.debug("Ignored StormGuard event with an unknown state")
        return None

    tracker.async_handle(event)
    return None
