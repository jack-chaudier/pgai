"""Run all scenarios sequentially against the PGAI test line.

Usage:
    1. Start server:  uvicorn src.server:app --port 8000
    2. Start ngrok:   ngrok http 8000
    3. Run batch:     python scripts/run_batch.py <ngrok_url> [--scenarios 1,2,5]

Each call waits for the previous to finish before starting the next.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TARGET = os.environ.get("TARGET_PHONE_NUMBER", "+18054398008")
SCENARIOS_FILE = Path(__file__).resolve().parent.parent / "scenarios" / "scenarios.json"

# Cost rates (approximate)
TWILIO_PER_MIN = 0.022  # outbound + media stream
NOVA_INPUT_PER_SEC = 0.0017
NOVA_OUTPUT_PER_SEC = 0.0068


def load_scenarios(filter_ids: list[str] | None = None) -> list[dict]:
    with open(SCENARIOS_FILE) as f:
        scenarios = json.load(f)
    if filter_ids:
        scenarios = [s for s in scenarios if s["id"] in filter_ids]
    return scenarios


def make_call(ngrok_url: str, scenario: dict, twilio_client: Client, from_number: str) -> str:
    """Set scenario on server and initiate Twilio call. Returns call SID."""
    # Set scenario on server
    resp = httpx.post(f"{ngrok_url}/set-scenario", json=scenario, timeout=10)
    resp.raise_for_status()

    # Make the call
    call = twilio_client.calls.create(
        to=TARGET,
        from_=from_number,
        url=f"{ngrok_url}/twilio/voice",
    )
    return call.sid


def wait_for_call(twilio_client: Client, call_sid: str, max_wait: int = 360) -> dict:
    """Poll Twilio until the call completes. Returns call details."""
    start = time.time()
    while time.time() - start < max_wait:
        call = twilio_client.calls(call_sid).fetch()
        if call.status in ("completed", "failed", "busy", "no-answer", "canceled"):
            return {
                "sid": call.sid,
                "status": call.status,
                "duration": int(call.duration or 0),
                "start_time": str(call.start_time),
                "end_time": str(call.end_time),
            }
        time.sleep(5)
    return {"sid": call_sid, "status": "timeout", "duration": 0}


def estimate_cost(duration_s: int) -> dict:
    """Estimate cost breakdown for a call."""
    twilio = (duration_s / 60) * TWILIO_PER_MIN
    nova_in = duration_s * NOVA_INPUT_PER_SEC
    nova_out = (duration_s * 0.25) * NOVA_OUTPUT_PER_SEC  # bot speaks ~25% of the time
    total = twilio + nova_in + nova_out
    return {
        "twilio": round(twilio, 3),
        "nova_sonic": round(nova_in + nova_out, 3),
        "total": round(total, 3),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_batch.py <ngrok_url> [--scenarios id1,id2,...]")
        sys.exit(1)

    ngrok_url = sys.argv[1].rstrip("/")

    # Parse optional scenario filter
    filter_ids = None
    for i, arg in enumerate(sys.argv):
        if arg == "--scenarios" and i + 1 < len(sys.argv):
            filter_ids = sys.argv[i + 1].split(",")

    scenarios = load_scenarios(filter_ids)
    print(f"Running {len(scenarios)} scenarios against {TARGET}")
    print(f"Server: {ngrok_url}")
    print()

    twilio_client = Client(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"],
    )
    from_number = os.environ["TWILIO_PHONE_NUMBER"].replace(" ", "")

    results = []
    total_cost = 0

    for i, scenario in enumerate(scenarios):
        print(f"[{i+1}/{len(scenarios)}] {scenario['name']}")
        print(f"  ID: {scenario['id']}")

        try:
            call_sid = make_call(ngrok_url, scenario, twilio_client, from_number)
            print(f"  Call SID: {call_sid}")
            print("  Waiting for call to complete...", end="", flush=True)

            call_info = wait_for_call(twilio_client, call_sid)
            duration = call_info["duration"]
            cost = estimate_cost(duration)
            total_cost += cost["total"]

            print(f" {call_info['status']} ({duration}s)")
            print(f"  Cost: ~${cost['total']:.3f} (Twilio: ${cost['twilio']:.3f}, Nova: ${cost['nova_sonic']:.3f})")

            results.append({
                "scenario": scenario["id"],
                "name": scenario["name"],
                "call": call_info,
                "cost": cost,
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "scenario": scenario["id"],
                "name": scenario["name"],
                "error": str(e),
            })

        # Brief pause between calls
        if i < len(scenarios) - 1:
            print(f"  Pausing 10s before next call...")
            time.sleep(10)

    # Summary
    print("\n" + "=" * 60)
    print("BATCH COMPLETE")
    print("=" * 60)
    print(f"Calls: {len(results)}")
    print(f"Total estimated cost: ${total_cost:.2f}")
    print()
    for r in results:
        status = r.get("call", {}).get("status", r.get("error", "?"))
        duration = r.get("call", {}).get("duration", 0)
        cost = r.get("cost", {}).get("total", 0)
        print(f"  {r['scenario']:30s} {status:12s} {duration:4d}s  ${cost:.3f}")

    # Save results
    Path("transcripts").mkdir(exist_ok=True)
    results_path = "transcripts/batch-results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    main()
