"""Bridge between Twilio media stream and Nova Sonic bidirectional stream."""

import asyncio
import base64
import json
import logging
import os
import time
import wave
from datetime import datetime

import numpy as np

from src.audio import nova_to_twilio, twilio_to_nova, mulaw_decode
from src.nova_sonic import NovaSonicSession, SENTINEL
from src.twilio_ws import TwilioStream

log = logging.getLogger(__name__)

GOODBYE_PHRASES = {"bye", "goodbye", "good bye", "have a great day", "take care"}
MAX_CALL_DURATION = 300  # seconds
SAMPLE_RATE = 8000  # recording sample rate


class TwilioNovaBridge:
    def __init__(self, twilio: TwilioStream, system_prompt: str, voice_id: str = "tiffany",
                 scenario_id: str = "default", scenario_name: str = ""):
        self.twilio = twilio
        self.nova = NovaSonicSession(system_prompt=system_prompt, voice_id=voice_id)
        self.transcript: list[dict] = []
        self.scenario_id = scenario_id
        self.scenario_name = scenario_name
        self._recent_texts: set[str] = set()
        # Audio timeline: list of (timestamp, direction, mulaw_bytes)
        self._audio_timeline: list[tuple[float, str, bytes]] = []
        self._call_start: float = 0
        self._goodbye_count = 0

    async def run(self) -> list[dict]:
        """Bridge audio between Twilio and Nova Sonic until the call ends."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.nova.start)
        self._call_start = time.monotonic()
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
                raw = base64.b64decode(payload)
                self._audio_timeline.append((time.monotonic(), "in", raw))
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
                raw = base64.b64decode(mulaw_b64)
                self._audio_timeline.append((time.monotonic(), "out", raw))
                await self.twilio.send_audio(mulaw_b64)

            elif event.type == "text":
                # Clean up: Nova sometimes includes newlines and multi-part text
                text = " ".join(event.data.split()).strip()
                if not text or text.startswith("{"):
                    continue
                # Map Nova roles to readable names
                nova_role = event.role or ""
                role = "AGENT" if nova_role == "USER" else "PATIENT"
                if text in self._recent_texts:
                    continue
                self._recent_texts.add(text)
                if len(self._recent_texts) > 200:
                    self._recent_texts.clear()
                # Merge consecutive same-role entries
                if self.transcript and self.transcript[-1]["role"] == role:
                    self.transcript[-1]["content"] += " " + text
                else:
                    self.transcript.append({"role": role, "content": text})
                log.info("[%s] %s", role, text[:120])
                self._check_goodbye(text)

            elif event.type == "turn_end":
                pass

    async def _max_duration_timer(self):
        await asyncio.sleep(MAX_CALL_DURATION)
        log.info("Max call duration reached (%ds) — ending call", MAX_CALL_DURATION)
        await self.twilio.ws.close()

    def _check_goodbye(self, text: str):
        lower = text.lower()
        if any(phrase in lower for phrase in GOODBYE_PHRASES):
            self._goodbye_count += 1
            if self._goodbye_count >= 2:
                log.info("Both sides said goodbye — ending call")
                asyncio.create_task(self.twilio.ws.close())

    def _save_call(self):
        """Save transcript JSON, readable text, and combined stereo WAV."""
        if not self.transcript:
            return

        call_duration = time.monotonic() - self._call_start if self._call_start else 0
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        prefix = f"transcripts/{self.scenario_id}-{ts}"
        os.makedirs("transcripts", exist_ok=True)

        # Save transcript JSON with metadata
        output = {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": round(call_duration, 1),
            "transcript": self.transcript,
        }
        json_path = f"{prefix}.json"
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)
        log.info("Transcript saved to %s", json_path)

        # Save readable text version
        txt_path = f"{prefix}.txt"
        with open(txt_path, "w") as f:
            f.write(f"Scenario: {self.scenario_name}\n")
            f.write(f"Duration: {call_duration:.0f}s\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write("=" * 60 + "\n\n")
            for entry in self.transcript:
                label = "Agent" if entry["role"] == "AGENT" else "Patient"
                f.write(f"{label}: {entry['content']}\n\n")
        log.info("Text transcript saved to %s", txt_path)

        if not self._audio_timeline:
            return

        # Build stereo WAV: left = inbound (PGAI agent), right = outbound (our bot)
        # Inbound audio is real-time paced (Twilio sends 20ms chunks at 20ms intervals)
        # so timestamps work. Outbound audio arrives in bursts from Nova, so we
        # track a running playback position instead.
        total_duration = self._audio_timeline[-1][0] - self._call_start + 0.5
        total_samples = int(total_duration * SAMPLE_RATE)
        left = np.zeros(total_samples, dtype=np.int16)   # inbound
        right = np.zeros(total_samples, dtype=np.int16)   # outbound
        out_pos = 0  # running write position for outbound

        for timestamp, direction, mulaw_bytes in self._audio_timeline:
            pcm = mulaw_decode(mulaw_bytes)
            if direction == "in":
                offset = int((timestamp - self._call_start) * SAMPLE_RATE)
                end = min(offset + len(pcm), total_samples)
                n = end - offset
                if n > 0 and offset >= 0:
                    left[offset:end] = pcm[:n]
            else:
                # For outbound, use timestamp for initial position but advance
                # sequentially within each burst to avoid overlap
                ts_offset = int((timestamp - self._call_start) * SAMPLE_RATE)
                offset = max(ts_offset, out_pos)
                end = min(offset + len(pcm), total_samples)
                n = end - offset
                if n > 0 and offset >= 0:
                    right[offset:end] = pcm[:n]
                    out_pos = offset + len(pcm)

        # Interleave stereo
        stereo = np.column_stack((left, right)).flatten()
        wav_path = f"{prefix}.wav"
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(stereo.tobytes())
        log.info("Audio saved to %s (%.1fs stereo)", wav_path, total_duration)
