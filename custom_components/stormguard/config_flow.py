"""Config and options flow.

The flow generates the webhook id (a secret), registers nothing itself and ends
on a pairing step that shows the deep link the StormGuard app opens, plus the
raw values for manual entry.
"""

from __future__ import annotations

from typing import Any

try:  # Home Assistant >= 2026.9 validates with probatio (voluptuous-compatible).
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import callback

from .const import (
    CONF_ALLOW_REMOTE,
    CONF_SAFETY_TIMEOUT,
    DEFAULT_ALLOW_REMOTE,
    DEFAULT_SAFETY_TIMEOUT,
    DOMAIN,
    MAX_SAFETY_TIMEOUT,
    MIN_SAFETY_TIMEOUT,
    NAME,
)
from .pairing import PairingInfo, async_pairing_info, generate_webhook_id


def _placeholders(info: PairingInfo, webhook_id: str) -> dict[str, str]:
    link = info.link or ""
    return {
        "link": f"[StormGuard ↗]({link})" if link else "—",
        "raw_link": link or "—",
        "base_url": info.base_url or "—",
        "remote_url": info.remote_url or "—",
        "webhook_id": webhook_id,
    }


def _errors(info: PairingInfo) -> dict[str, str] | None:
    return {"base": info.problem} if info.problem else None


class StormGuardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._webhook_id: str | None = None
        self._allow_remote = DEFAULT_ALLOW_REMOTE

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask whether events may come from outside the home network."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_ALLOW_REMOTE, default=DEFAULT_ALLOW_REMOTE): bool}
                ),
            )

        self._allow_remote = bool(user_input[CONF_ALLOW_REMOTE])
        self._webhook_id = generate_webhook_id()
        return await self.async_step_pair()

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the pairing link; submitting creates the entry."""
        assert self._webhook_id is not None
        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={CONF_WEBHOOK_ID: self._webhook_id},
                options={
                    CONF_ALLOW_REMOTE: self._allow_remote,
                    CONF_SAFETY_TIMEOUT: DEFAULT_SAFETY_TIMEOUT,
                },
            )

        info = async_pairing_info(self.hass, self._webhook_id, self._allow_remote)
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            description_placeholders=_placeholders(info, self._webhook_id),
            errors=_errors(info),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> StormGuardOptionsFlow:
        """Return the options flow."""
        return StormGuardOptionsFlow()


class StormGuardOptionsFlow(OptionsFlow):
    """Safety timeout and remote access; also shows the pairing link again."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SAFETY_TIMEOUT: int(user_input[CONF_SAFETY_TIMEOUT]),
                    CONF_ALLOW_REMOTE: bool(user_input[CONF_ALLOW_REMOTE]),
                }
            )

        options = self.config_entry.options
        allow_remote = bool(options.get(CONF_ALLOW_REMOTE, DEFAULT_ALLOW_REMOTE))
        webhook_id: str = self.config_entry.data[CONF_WEBHOOK_ID]
        info = async_pairing_info(self.hass, webhook_id, allow_remote)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SAFETY_TIMEOUT,
                    default=int(options.get(CONF_SAFETY_TIMEOUT, DEFAULT_SAFETY_TIMEOUT)),
                ): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SAFETY_TIMEOUT, max=MAX_SAFETY_TIMEOUT)
                ),
                vol.Required(CONF_ALLOW_REMOTE, default=allow_remote): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders=_placeholders(info, webhook_id),
        )
