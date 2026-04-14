"""Saturday assist satellite entity."""

from __future__ import annotations

import asyncio
import json
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

from .const import (
    CONF_FCM_PROJECT_ID,
    CONF_FCM_SERVICE_ACCOUNT,
    CONF_NTFY_TOPIC,
    CONF_NTFY_URL,
    CONF_SERVER_URL,
    DEFAULT_CALL_TIMEOUT,
    DOMAIN,
    FCM_TOPIC,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Saturday satellite entity from a config entry."""
    async_add_entities([SaturdaySatellite(hass, entry)])


class SaturdaySatellite(AssistSatelliteEntity):
    """A web-based voice satellite that uses ntfy + FCM for push notifications."""

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

        # FCM config (optional)
        self._fcm_project_id: str | None = entry.data.get(CONF_FCM_PROJECT_ID)
        self._fcm_service_account: str | None = entry.data.get(CONF_FCM_SERVICE_ACCOUNT)

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data.get("name", "Saturday"),
            "manufacturer": "Saturday",
            "model": "Web Voice Satellite",
        }

    @property
    def _fcm_enabled(self) -> bool:
        """Check if FCM is configured."""
        return bool(self._fcm_project_id and self._fcm_service_account)

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
        """Handle pipeline events (no-op)."""

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        """Play an announcement on the satellite."""
        await self._send_call(announcement, "announce")

    async def async_start_conversation(
        self, announcement: AssistSatelliteAnnouncement
    ) -> None:
        """Play an announcement and start a conversation."""
        await self._send_call(announcement, "start_conversation")

    async def _send_call(
        self, announcement: AssistSatelliteAnnouncement, call_type: str
    ) -> None:
        """Send a call notification via ntfy + FCM and wait for ACK."""
        call_id = uuid4().hex
        event = asyncio.Event()
        self._pending_calls[call_id] = event

        try:
            # Build the call URL with all data as query params
            params = {
                "callId": call_id,
                "type": call_type,
                "webhookId": self._webhook_id,
            }
            if announcement.message:
                params["text"] = announcement.message
            if announcement.media_id:
                params["media"] = announcement.media_id

            call_url = f"{self._server_url}/call?{urlencode(params, quote_via=quote)}"

            async with aiohttp.ClientSession() as session:
                # Send FCM push (triggers native call screen)
                if self._fcm_enabled:
                    await self._send_fcm(
                        session, call_id, call_url,
                        announcement.message or "Incoming call",
                    )

                # Send ntfy notification (fallback / non-native path)
                await self._send_ntfy(
                    session, call_id, call_url,
                    announcement.message or "Incoming call",
                )

            _LOGGER.info(
                "Call %s published (fcm=%s, ntfy=%s), waiting for ACK",
                call_id, self._fcm_enabled, self._ntfy_topic,
            )

            await asyncio.wait_for(event.wait(), timeout=DEFAULT_CALL_TIMEOUT)
            _LOGGER.info("Call %s acknowledged", call_id)

        except TimeoutError:
            _LOGGER.warning("Call %s timed out after %ds", call_id, DEFAULT_CALL_TIMEOUT)
            raise HomeAssistantError(
                f"Saturday did not acknowledge the call within {DEFAULT_CALL_TIMEOUT}s"
            )
        finally:
            self._pending_calls.pop(call_id, None)

    async def _send_ntfy(
        self, session: aiohttp.ClientSession,
        call_id: str, call_url: str, message: str,
    ) -> None:
        """Publish notification to ntfy."""
        ntfy_payload = {
            "topic": self._ntfy_topic,
            "title": "Saturday",
            "message": message,
            "click": call_url,
            "tags": ["phone"],
            "priority": 4,
        }

        try:
            async with session.post(
                self._ntfy_url,
                json=ntfy_payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    _LOGGER.error("ntfy publish failed: %s %s", resp.status, body)
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("ntfy publish error: %s", err)

    async def _send_fcm(
        self, session: aiohttp.ClientSession,
        call_id: str, call_url: str, message: str,
    ) -> None:
        """Send FCM high-priority data message to trigger native call screen."""
        try:
            access_token = await self._get_fcm_access_token(session)

            fcm_payload = {
                "message": {
                    "topic": FCM_TOPIC,
                    "data": {
                        "type": "incoming_call",
                        "call_id": call_id,
                        "call_url": call_url,
                        "caller_name": "Saturday",
                        "message": message,
                    },
                    "android": {
                        "priority": "high",
                        "ttl": "30s",
                    },
                }
            }

            url = f"https://fcm.googleapis.com/v1/projects/{self._fcm_project_id}/messages:send"

            async with session.post(
                url,
                json=fcm_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    _LOGGER.error("FCM send failed: %s %s", resp.status, body)
                else:
                    _LOGGER.debug("FCM message sent for call %s", call_id)
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("FCM send error: %s", err)

    async def _get_fcm_access_token(self, session: aiohttp.ClientSession) -> str:
        """Get an OAuth2 access token for FCM using a service account."""
        import time
        import hashlib
        import hmac
        import base64

        sa = json.loads(self._fcm_service_account)
        now = int(time.time())

        # Build JWT
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()

        payload = base64.urlsafe_b64encode(
            json.dumps({
                "iss": sa["client_email"],
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
                "aud": "https://oauth2.googleapis.com/token",
                "iat": now,
                "exp": now + 3600,
            }).encode()
        ).rstrip(b"=").decode()

        signing_input = f"{header}.{payload}"

        # Sign with RSA private key
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(
            sa["private_key"].encode(), password=None
        )
        signature = private_key.sign(
            signing_input.encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

        jwt_token = f"{signing_input}.{sig_b64}"

        # Exchange JWT for access token
        async with session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt_token,
            },
        ) as resp:
            token_data = await resp.json()
            return token_data["access_token"]
