"""Verify Nova Sonic connection works (threaded architecture).

Usage:
    source .venv/bin/activate
    python scripts/test_nova_sonic.py
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.nova_sonic import NovaSonicSession

SYSTEM_PROMPT = "You are a friendly assistant. Say hello briefly."


def main():
    print("1. Starting Nova Sonic session...", flush=True)
    session = NovaSonicSession(system_prompt=SYSTEM_PROMPT)
    session.start()
    print("   OK — connected", flush=True)

    print("2. Checking for events (5s)...", flush=True)
    end = time.time() + 5
    count = 0
    while time.time() < end:
        event = session.get_event(timeout=0.1)
        if event is None:
            continue
        print(f"   [{event.type}] role={event.role} data={event.data[:60] if event.data else ''}", flush=True)
        count += 1
        if event.type == "turn_end" or count > 10:
            break

    session.stop()
    print(f"\nConnection test PASSED ({count} events).", flush=True)


if __name__ == "__main__":
    main()
