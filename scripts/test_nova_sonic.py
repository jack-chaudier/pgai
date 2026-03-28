"""Standalone test: connect to Nova Sonic, send silence, capture audio response.

Usage:
    source .venv/bin/activate
    python scripts/test_nova_sonic.py

Requires AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env or environment.
Writes output to scripts/nova_test_output.wav for manual listening.
"""

import asyncio
import base64
import struct
import sys
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.nova_sonic import NovaSonicSession

load_dotenv()

SYSTEM_PROMPT = (
    "You are a friendly person answering the phone. "
    "Say hello and ask how you can help. Keep it brief — one or two sentences."
)


async def main():
    print("Connecting to Nova Sonic...")
    session = NovaSonicSession(system_prompt=SYSTEM_PROMPT)
    await session.connect()
    print("Connected. Sending 2 seconds of silence to prompt a response...")

    # Send 2 seconds of silence (16kHz PCM16 = 32000 samples = 64000 bytes)
    silence = np.zeros(32000, dtype=np.int16)
    chunk_size = 3200  # 200ms chunks
    for i in range(0, len(silence), chunk_size):
        chunk = silence[i : i + chunk_size]
        b64 = base64.b64encode(chunk.tobytes()).decode("ascii")
        await session.send_audio(b64)
        await asyncio.sleep(0.02)  # pace the sends

    print("Silence sent. Waiting for response...")

    audio_chunks: list[bytes] = []
    transcripts: list[str] = []

    try:
        async for event in session.receive_events():
            if event.type == "audio":
                audio_bytes = base64.b64decode(event.data)
                audio_chunks.append(audio_bytes)
                print(f"  [audio] {len(audio_bytes)} bytes")
            elif event.type == "text":
                transcripts.append(f"[{event.role}] {event.data}")
                print(f"  [text] [{event.role}] {event.data}")
            elif event.type == "turn_end":
                print("  [turn_end]")
                break
    except Exception as e:
        print(f"Error during receive: {e}")
    finally:
        await session.close()

    # Write captured audio to WAV (24kHz PCM16 mono)
    if audio_chunks:
        all_audio = b"".join(audio_chunks)
        out_path = Path(__file__).parent / "nova_test_output.wav"
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(all_audio)
        print(f"\nAudio written to {out_path} ({len(all_audio)} bytes, {len(all_audio)/48000:.1f}s)")
    else:
        print("\nNo audio received.")

    if transcripts:
        print("\nTranscripts:")
        for t in transcripts:
            print(f"  {t}")
    else:
        print("\nNo transcripts received.")


if __name__ == "__main__":
    asyncio.run(main())
