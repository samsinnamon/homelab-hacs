"""Config flow for Saturday Voice Satellite."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_NAME

from .const import CONF_NTFY_TOPIC, CONF_NTFY_URL, CONF_SERVER_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Saturday"): str,
        vol.Required(CONF_SERVER_URL, default="https://sat.example.com"): str,
        vol.Required(CONF_NTFY_URL, default="https://ntfy.example.com"): str,
        vol.Required(CONF_NTFY_TOPIC, default="saturday"): str,
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
            # Validate connectivity to Saturday server
            server_url = user_input[CONF_SERVER_URL].rstrip("/")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{server_url}/api/health", timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

            if not errors:
                # Generate a unique webhook ID for this entry
                user_input["webhook_id"] = f"saturday_{uuid4().hex[:8]}"
                user_input[CONF_SERVER_URL] = server_url

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
