# Saturday Voice Satellite

A Home Assistant custom integration that registers a web-based voice satellite for the [Saturday](https://github.com/pegasus-home-lab/saturday) voice assistant.

Saturday is a web-based Home Assistant Assist satellite. This integration registers it as a proper `assist_satellite` entity so HA automations can initiate conversations with the user via ntfy push notifications.

## How it works

1. An HA automation calls `assist_satellite.start_conversation` on the Saturday entity
2. The integration publishes a notification to ntfy with the announcement details
3. The user's phone rings and they tap the notification to open Saturday
4. Saturday plays the announcement and starts a two-way voice conversation
5. Once the announcement finishes playing, the integration signals completion back to HA

## Configuration

Add the integration via Settings > Devices & Services > Add Integration > Saturday Voice Satellite.

You will need:
- **Satellite name** - display name for the device
- **Saturday server URL** - e.g., `https://sat.example.com`
- **ntfy server URL** - e.g., `https://ntfy.example.com`
- **ntfy topic** - the topic to publish notifications to
