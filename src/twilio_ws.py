"""Twilio Media Streams WebSocket handler."""

import json
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class TwilioStream:
    ws: WebSocket
    stream_sid: str = ""
    call_sid: str = ""

    async def run(self):
        """Yield (event_type, payload) tuples from Twilio.

        event_type is one of: "start", "media", "stop", "dtmf", "mark".
        For "media", payload is the base64-encoded mulaw audio string.
        For others, payload is the raw parsed dict.
        """
        async for raw in self.ws.iter_text():
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "start":
                self.stream_sid = msg["start"]["streamSid"]
                self.call_sid = msg["start"]["callSid"]
                yield "start", msg["start"]

            elif event == "media":
                yield "media", msg["media"]["payload"]

            elif event == "stop":
                yield "stop", msg.get("stop", {})
                return

            elif event == "mark":
                yield "mark", msg.get("mark", {})

            elif event == "dtmf":
                yield "dtmf", msg.get("dtmf", {})

    async def send_audio(self, mulaw_b64: str) -> None:
        """Send audio back to Twilio."""
        await self.ws.send_text(json.dumps({
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": mulaw_b64},
        }))

    async def send_clear(self) -> None:
        """Clear Twilio's audio playback buffer (for barge-in)."""
        await self.ws.send_text(json.dumps({
            "event": "clear",
            "streamSid": self.stream_sid,
        }))

    async def send_mark(self, name: str) -> None:
        """Send a mark to track when audio playback completes."""
        await self.ws.send_text(json.dumps({
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {"name": name},
        }))
