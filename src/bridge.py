"""Bridge between Twilio media stream and Nova Sonic bidirectional stream."""

import asyncio
import base64
import json
import logging
import os
import wave
from datetime import datetime

from src.audio import nova_to_twilio, twilio_to_nova, mulaw_decode
from src.nova_sonic import NovaSonicSession, SENTINEL
from src.twilio_ws import TwilioStream

log = logging.getLogger(__name__)

GOODBYE_PHRASES = {"bye", "goodbye", "good bye", "have a great day", "take care"}
MAX_CALL_DURATION = 180  # seconds


class TwilioNovaBridge:
    def __init__(self, twilio: TwilioStream, system_prompt: str, voice_id: str = "matthew"):
        self.twilio = twilio
        self.nova = NovaSonicSession(system_prompt=system_prompt, voice_id=voice_id)
        self.transcript: list[dict] = []
        self._recent_texts: set[str] = set()
        self._inbound_audio: list[bytes] = []  # raw mulaw from Twilio
        self._outbound_audio: list[bytes] = []  # raw mulaw sent to Twilio
        self._goodbye_count = 0

    async def run(self) -> list[dict]:
        """Bridge audio between Twilio and Nova Sonic until the call ends."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.nova.start)
        log.info("Nova Sonic connected, bridging audio")

        tasks = [
            asyncio.create_task(self._twilio_to_nova(), name="twilio→nova"),
            asyncio.create_task(self._nova_to_twilio(), name="nova→twilio"),
            asyncio.create_task(self._max_duration_timer(), name="timer"),
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

        self._save_call()
        return self.transcript

    async def _twilio_to_nova(self):
        """Forward Twilio audio to Nova Sonic."""
        media_count = 0
        async for event_type, payload in self.twilio.run():
            if event_type == "start":
                log.info("Call started: stream=%s call=%s", self.twilio.stream_sid, self.twilio.call_sid)
            elif event_type == "media":
                media_count += 1
                # Save raw mulaw for recording
                self._inbound_audio.append(base64.b64decode(payload))
                nova_audio = twilio_to_nova(payload)
                self.nova.send_audio(nova_audio)
            elif event_type == "stop":
                log.info("Call ended (%d audio chunks)", media_count)
                return

    async def _nova_to_twilio(self):
        """Forward Nova Sonic audio to Twilio, collect transcript."""
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, lambda: self.nova.get_event(timeout=0.05))
            if event is SENTINEL:
                return
            if event is None:
                continue

            if event.type == "audio":
                mulaw_b64 = nova_to_twilio(event.data)
                self._outbound_audio.append(base64.b64decode(mulaw_b64))
                await self.twilio.send_audio(mulaw_b64)

            elif event.type == "text":
                text = event.data.strip()
                if not text or text.startswith("{"):
                    continue
                role = event.role or ""
                if text in self._recent_texts:
                    continue
                self._recent_texts.add(text)
                if len(self._recent_texts) > 50:
                    self._recent_texts.clear()
                self.transcript.append({"role": role, "content": text})
                log.info("[%s] %s", role, text[:120])
                self._check_goodbye(text)

            elif event.type == "turn_end":
                pass

    async def _max_duration_timer(self):
        """Safety net: end the call after MAX_CALL_DURATION seconds."""
        await asyncio.sleep(MAX_CALL_DURATION)
        log.info("Max call duration reached (%ds) — ending call", MAX_CALL_DURATION)
        await self.twilio.ws.close()

    def _check_goodbye(self, text: str):
        """Track goodbye signals from both sides."""
        lower = text.lower()
        if any(phrase in lower for phrase in GOODBYE_PHRASES):
            self._goodbye_count += 1
            if self._goodbye_count >= 2:
                log.info("Both sides said goodbye — ending call")
                # Close the WebSocket to end the call
                asyncio.create_task(self.twilio.ws.close())

    def _save_call(self):
        """Save transcript and audio recordings."""
        if not self.transcript:
            return

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        os.makedirs("transcripts", exist_ok=True)

        # Save transcript JSON
        transcript_path = f"transcripts/call-{ts}.json"
        with open(transcript_path, "w") as f:
            json.dump(self.transcript, f, indent=2)
        log.info("Transcript saved to %s", transcript_path)

        # Save audio recordings as WAV (8kHz mulaw → 8kHz PCM16)
        for label, chunks in [("inbound", self._inbound_audio), ("outbound", self._outbound_audio)]:
            if not chunks:
                continue
            raw = b"".join(chunks)
            pcm = mulaw_decode(raw)
            wav_path = f"transcripts/call-{ts}-{label}.wav"
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm.tobytes())
            log.info("Audio saved to %s (%.1fs)", wav_path, len(pcm) / 8000)
