"""Bridge between Twilio media stream and Nova Sonic bidirectional stream."""

import asyncio
import logging

from src.audio import nova_to_twilio, twilio_to_nova
from src.nova_sonic import NovaSonicSession
from src.twilio_ws import TwilioStream

log = logging.getLogger(__name__)


class TwilioNovaBridge:
    def __init__(self, twilio: TwilioStream, system_prompt: str, voice_id: str = "matthew"):
        self.twilio = twilio
        self.nova = NovaSonicSession(system_prompt=system_prompt, voice_id=voice_id)
        self.transcript: list[dict] = []
        self._current_role: str = ""
        self._nova_ready = asyncio.Event()

    async def run(self) -> list[dict]:
        """Bridge audio between Twilio and Nova Sonic until the call ends."""
        tasks = [
            asyncio.create_task(self._connect_nova(), name="nova-connect"),
            asyncio.create_task(self._twilio_to_nova(), name="twilio→nova"),
            asyncio.create_task(self._nova_to_twilio(), name="nova→twilio"),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                if t.exception():
                    log.error("Task %s failed: %s", t.get_name(), t.exception())
        finally:
            await self.nova.close()

        return self.transcript

    async def _connect_nova(self):
        """Connect to Nova Sonic and signal readiness."""
        log.info("Connecting to Nova Sonic...")
        await self.nova.connect()
        log.info("Nova Sonic connected")
        self._nova_ready.set()
        # Keep this task alive (it completes when other tasks cancel it)
        await asyncio.Event().wait()

    async def _twilio_to_nova(self):
        """Forward Twilio audio to Nova Sonic."""
        async for event_type, payload in self.twilio.run():
            if event_type == "start":
                log.info("Call started: stream=%s call=%s", self.twilio.stream_sid, self.twilio.call_sid)
            elif event_type == "media":
                if self._nova_ready.is_set():
                    nova_audio = twilio_to_nova(payload)
                    await self.nova.send_audio(nova_audio)
            elif event_type == "stop":
                log.info("Call ended")
                return

    async def _nova_to_twilio(self):
        """Forward Nova Sonic audio to Twilio, collect transcript."""
        await self._nova_ready.wait()
        async for event in self.nova.receive_events():
            if event.type == "audio":
                twilio_audio = nova_to_twilio(event.data)
                await self.twilio.send_audio(twilio_audio)

            elif event.type == "text_start":
                self._current_role = event.role

            elif event.type == "text":
                role = event.role or self._current_role
                self.transcript.append({"role": role, "content": event.data})
                log.info("[%s] %s", role, event.data[:80])

            elif event.type == "turn_end":
                log.info("Turn complete")
