"""Bridge between Twilio media stream and Nova Sonic bidirectional stream."""

import asyncio
import json
import logging
import os
import time
from datetime import datetime

from src.audio import nova_to_twilio, twilio_to_nova
from src.nova_sonic import NovaSonicSession, SENTINEL
from src.twilio_ws import TwilioStream

log = logging.getLogger(__name__)


class TwilioNovaBridge:
    def __init__(self, twilio: TwilioStream, system_prompt: str, voice_id: str = "matthew"):
        self.twilio = twilio
        self.nova = NovaSonicSession(system_prompt=system_prompt, voice_id=voice_id)
        self.transcript: list[dict] = []
        self._recent_texts: set[str] = set()  # sliding dedup window

    async def run(self) -> list[dict]:
        """Bridge audio between Twilio and Nova Sonic until the call ends."""
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
            for t in pending:
                t.cancel()
        finally:
            self.nova.stop()

        self._save_transcript()
        return self.transcript

    async def _twilio_to_nova(self):
        """Forward Twilio audio to Nova Sonic."""
        media_count = 0
        async for event_type, payload in self.twilio.run():
            if event_type == "start":
                log.info("Call started: stream=%s call=%s", self.twilio.stream_sid, self.twilio.call_sid)
            elif event_type == "media":
                media_count += 1
                if media_count % 500 == 0:
                    log.info("Twilio→Nova: %d chunks", media_count)
                nova_audio = twilio_to_nova(payload)
                self.nova.send_audio(nova_audio)
            elif event_type == "stop":
                log.info("Call ended (%d audio chunks)", media_count)
                return

    async def _nova_to_twilio(self):
        """Forward Nova Sonic audio to Twilio, collect transcript."""
        loop = asyncio.get_event_loop()
        audio_out_count = 0
        while True:
            event = await loop.run_in_executor(None, lambda: self.nova.get_event(timeout=0.05))
            if event is SENTINEL:
                return
            if event is None:
                continue

            if event.type == "audio":
                audio_out_count += 1
                if audio_out_count % 200 == 0:
                    log.info("Nova→Twilio: %d audio chunks", audio_out_count)
                twilio_audio = nova_to_twilio(event.data)
                await self.twilio.send_audio(twilio_audio)

            elif event.type == "text":
                text = event.data.strip()
                if not text or text.startswith("{"):
                    continue
                role = event.role or ""
                # Deduplicate: Nova sends each response text twice
                if text in self._recent_texts:
                    continue
                self._recent_texts.add(text)
                # Keep window from growing forever
                if len(self._recent_texts) > 50:
                    self._recent_texts.clear()
                self.transcript.append({"role": role, "content": text})
                log.info("[%s] %s", role, text[:120])

            elif event.type == "turn_end":
                log.info("Turn complete")

    def _save_transcript(self):
        """Save transcript to transcripts/ directory."""
        if not self.transcript:
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = f"transcripts/call-{ts}.json"
        os.makedirs("transcripts", exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.transcript, f, indent=2)
        log.info("Transcript saved to %s", path)
