"""Verify Nova Sonic connection works: connect, send setup events, send audio.

Nova won't generate speech in response to silence — a real voice response
requires actual speech input (which happens via Twilio in production).
This test validates the SDK wiring and session lifecycle only.

Usage:
    source .venv/bin/activate
    python scripts/test_nova_sonic.py
"""

import asyncio
import base64
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from src.nova_sonic import NovaSonicSession

SYSTEM_PROMPT = (
    "You are a patient calling a doctor's office. "
    "Start by saying hello and asking to schedule an appointment."
)


async def main():
    print("1. Connecting to Nova Sonic...", flush=True)
    session = NovaSonicSession(system_prompt=SYSTEM_PROMPT)
    await session.connect()
    print("   OK — stream open, session started", flush=True)

    print("2. Sending 1s of silence...", flush=True)
    chunk = np.zeros(1600, dtype=np.int16)  # 100ms at 16kHz
    b64 = base64.b64encode(chunk.tobytes()).decode("ascii")
    for _ in range(10):
        await session.send_audio(b64)
        await asyncio.sleep(0.1)
    print("   OK — audio accepted without errors", flush=True)

    print("3. Checking output stream (5s timeout)...", flush=True)
    event_count = 0
    try:
        async with asyncio.timeout(5):
            async for event in session.receive_events():
                print(f"   [{event.type}] role={event.role}", flush=True)
                event_count += 1
                if event.type == "turn_end" or event_count > 10:
                    break
    except TimeoutError:
        print("   Timed out (expected — Nova needs real speech to respond)", flush=True)

    await session.close()
    print("\nConnection test PASSED.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
