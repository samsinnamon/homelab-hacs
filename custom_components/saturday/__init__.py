"""Saturday Voice Satellite integration."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp.web import Request, Response

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["assist_satellite"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Saturday Voice Satellite from a config entry."""
    webhook_id = entry.data["webhook_id"]

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "pending_calls": {},
        "webhook_id": webhook_id,
    }

    webhook.async_register(
        hass, DOMAIN, "Saturday ACK", webhook_id, _handle_ack
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    webhook_id = entry.data["webhook_id"]
    webhook.async_unregister(hass, webhook_id)

    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False


async def _handle_ack(
    hass: HomeAssistant, webhook_id: str, request: Request
) -> Response:
    """Handle ACK webhook from Saturday server."""
    try:
        body: dict[str, Any] = await request.json()
    except (ValueError, KeyError):
        return Response(status=400)

    call_id = body.get("call_id")
    if not call_id:
        return Response(status=400)

    # Find and set the matching pending call event
    for entry_data in hass.data.get(DOMAIN, {}).values():
        pending = entry_data.get("pending_calls", {})
        event = pending.get(call_id)
        if event is not None:
            event.set()
            _LOGGER.debug("ACK received for call %s", call_id)
            return Response(status=200)

    _LOGGER.warning("ACK received for unknown call %s", call_id)
    return Response(status=404)
