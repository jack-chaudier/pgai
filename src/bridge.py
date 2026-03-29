"""Bridge between Twilio media stream and Nova Sonic bidirectional stream."""

import asyncio
import logging

from src.audio import nova_to_twilio, twilio_to_nova
from src.nova_sonic import NovaSonicSession, SENTINEL
from src.twilio_ws import TwilioStream

log = logging.getLogger(__name__)


class TwilioNovaBridge:
    def __init__(self, twilio: TwilioStream, system_prompt: str, voice_id: str = "matthew"):
        self.twilio = twilio
        self.nova = NovaSonicSession(system_prompt=system_prompt, voice_id=voice_id)
        self.transcript: list[dict] = []
        self._current_role: str = ""

    async def run(self) -> list[dict]:
        """Bridge audio between Twilio and Nova Sonic until the call ends."""
        # Start Nova in background thread (blocks until connected)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.nova.start)
        log.info("Nova Sonic connected, bridging audio")

        tasks = [
            asyncio.create_task(self._twilio_to_nova(), name="twilio→nova"),
            asyncio.create_task(self._nova_to_twilio(), name="nova→twilio"),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc:
                    log.error("Task %s failed: %s", t.get_name(), exc)
                else:
                    log.info("Task %s completed normally", t.get_name())
            for t in pending:
                log.info("Cancelling task %s", t.get_name())
                t.cancel()
        finally:
            self.nova.stop()

        return self.transcript

    async def _twilio_to_nova(self):
        """Forward Twilio audio to Nova Sonic."""
        media_count = 0
        async for event_type, payload in self.twilio.run():
            if event_type == "start":
                log.info("Call started: stream=%s call=%s", self.twilio.stream_sid, self.twilio.call_sid)
            elif event_type == "media":
                media_count += 1
                if media_count <= 3 or media_count % 50 == 0:
                    log.info("Twilio→Nova audio chunk #%d", media_count)
                nova_audio = twilio_to_nova(payload)
                self.nova.send_audio(nova_audio)
            elif event_type == "stop":
                log.info("Call ended (received %d audio chunks)", media_count)
                return

    async def _nova_to_twilio(self):
        """Forward Nova Sonic audio to Twilio, collect transcript."""
        loop = asyncio.get_event_loop()
        audio_out_count = 0
        while True:
            event = await loop.run_in_executor(None, lambda: self.nova.get_event(timeout=0.05))
            if event is SENTINEL:
                log.info("Nova sent shutdown sentinel")
                return
            if event is None:
                continue

            if event.type == "audio":
                audio_out_count += 1
                if audio_out_count <= 3 or audio_out_count % 50 == 0:
                    log.info("Nova→Twilio audio chunk #%d", audio_out_count)
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
