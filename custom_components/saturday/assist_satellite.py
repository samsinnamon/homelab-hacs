"""Saturday assist satellite entity."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlencode
from uuid import uuid4

import aiohttp

from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NTFY_TOPIC, CONF_NTFY_URL, CONF_SERVER_URL, DEFAULT_CALL_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saturday satellite entity from a config entry."""
    async_add_entities([SaturdaySatellite(hass, entry)])


class SaturdaySatellite(AssistSatelliteEntity):
    """A web-based voice satellite that uses ntfy for push notifications."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        AssistSatelliteEntityFeature.ANNOUNCE
        | AssistSatelliteEntityFeature.START_CONVERSATION
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the satellite."""
        self._entry = entry
        self._server_url: str = entry.data[CONF_SERVER_URL]
        self._ntfy_url: str = entry.data[CONF_NTFY_URL].rstrip("/")
        self._ntfy_topic: str = entry.data[CONF_NTFY_TOPIC]
        self._webhook_id: str = entry.data["webhook_id"]

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data.get("name", "Saturday"),
            "manufacturer": "Saturday",
            "model": "Web Voice Satellite",
        }

    @property
    def _pending_calls(self) -> dict[str, asyncio.Event]:
        """Get the pending calls dict from hass.data."""
        return self.hass.data[DOMAIN][self._entry.entry_id]["pending_calls"]

    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        """Return satellite configuration."""
        return AssistSatelliteConfiguration(
            available_wake_words=[],
            active_wake_words=[],
            max_active_wake_words=0,
        )

    async def async_set_configuration(
        self, config: AssistSatelliteConfiguration
    ) -> None:
        """Set satellite configuration (no-op for web satellite)."""

    def on_pipeline_event(self, event) -> None:
        """Handle pipeline events (no-op - pipeline runs through Saturday's own connection)."""

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        """Play an announcement on the satellite via ntfy push."""
        await self._send_call(announcement, "announce")

    async def async_start_conversation(
        self, announcement: AssistSatelliteAnnouncement
    ) -> None:
        """Play an announcement and start a conversation via ntfy push."""
        await self._send_call(announcement, "start_conversation")

    async def _send_call(
        self, announcement: AssistSatelliteAnnouncement, call_type: str
    ) -> None:
        """Send a call notification via ntfy and wait for the browser to ACK."""
        call_id = uuid4().hex
        event = asyncio.Event()
        self._pending_calls[call_id] = event

        try:
            # Build the click URL with all call data as query params
            params = {
                "callId": call_id,
                "type": call_type,
                "webhookId": self._webhook_id,
            }
            if announcement.message:
                params["text"] = announcement.message
            if announcement.media_id:
                params["media"] = announcement.media_id

            click_url = f"{self._server_url}/call?{urlencode(params, quote_via=quote)}"

            # Publish to ntfy
            ntfy_payload = {
                "topic": self._ntfy_topic,
                "title": "Saturday",
                "message": announcement.message or "Incoming call",
                "click": click_url,
                "tags": ["phone"],
                "priority": 4,  # high
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._ntfy_url,
                    json=ntfy_payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        raise HomeAssistantError(
                            f"Failed to publish ntfy notification: {resp.status} {body}"
                        )

            _LOGGER.info(
                "Call %s published to ntfy topic %s, waiting for ACK",
                call_id,
                self._ntfy_topic,
            )

            # Wait for the browser to ACK after playing the announcement
            await asyncio.wait_for(event.wait(), timeout=DEFAULT_CALL_TIMEOUT)
            _LOGGER.info("Call %s acknowledged", call_id)

        except TimeoutError:
            _LOGGER.warning("Call %s timed out after %ds", call_id, DEFAULT_CALL_TIMEOUT)
            raise HomeAssistantError(
                f"Saturday did not acknowledge the call within {DEFAULT_CALL_TIMEOUT}s"
            )
        finally:
            self._pending_calls.pop(call_id, None)
