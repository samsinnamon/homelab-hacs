"""Config flow for Saturday Voice Satellite."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_FCM_PROJECT_ID,
    CONF_FCM_SERVICE_ACCOUNT,
    CONF_NTFY_TOPIC,
    CONF_NTFY_URL,
    CONF_SERVER_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the config schema with optional defaults from existing config."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "Saturday")): selector.TextSelector(),
            vol.Required(CONF_SERVER_URL, default=d.get(CONF_SERVER_URL, "https://sat.example.com")): selector.TextSelector(),
            vol.Required(CONF_NTFY_URL, default=d.get(CONF_NTFY_URL, "https://ntfy.example.com")): selector.TextSelector(),
            vol.Required(CONF_NTFY_TOPIC, default=d.get(CONF_NTFY_TOPIC, "saturday")): selector.TextSelector(),
            vol.Optional(CONF_FCM_PROJECT_ID, default=d.get(CONF_FCM_PROJECT_ID, "")): selector.TextSelector(),
            vol.Optional(CONF_FCM_SERVICE_ACCOUNT, default=d.get(CONF_FCM_SERVICE_ACCOUNT, "")): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        }
    )


class SaturdayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Saturday Voice Satellite."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            server_url = user_input[CONF_SERVER_URL].rstrip("/")
            errors = await self._validate_server(server_url)

            if not errors:
                user_input["webhook_id"] = f"saturday_{uuid4().hex[:8]}"
                user_input[CONF_SERVER_URL] = server_url

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            server_url = user_input[CONF_SERVER_URL].rstrip("/")
            errors = await self._validate_server(server_url)

            if not errors:
                user_input[CONF_SERVER_URL] = server_url
                # Preserve the existing webhook_id
                user_input["webhook_id"] = entry.data.get(
                    "webhook_id", f"saturday_{uuid4().hex[:8]}"
                )

                return self.async_update_reload_and_abort(
                    entry,
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_schema(dict(entry.data)),
            errors=errors,
        )

    async def _validate_server(self, server_url: str) -> dict[str, str]:
        """Validate connectivity to Saturday server."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{server_url}/api/health", timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return {"base": "cannot_connect"}
        except (aiohttp.ClientError, TimeoutError):
            return {"base": "cannot_connect"}
        return {}
