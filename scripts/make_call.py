"""Make a test call to the PGAI test line via Twilio.

Usage:
    1. Start server:  uvicorn src.server:app --port 8000
    2. Start ngrok:   ngrok http 8000
    3. Run this:      python scripts/make_call.py <ngrok_url>

    Example: python scripts/make_call.py https://abc123.ngrok.app
"""

import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TARGET = os.environ.get("TARGET_PHONE_NUMBER", "+18054398008")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/make_call.py <ngrok_url>")
        print("Example: python scripts/make_call.py https://abc123.ngrok.app")
        sys.exit(1)

    ngrok_url = sys.argv[1].rstrip("/")
    webhook_url = f"{ngrok_url}/twilio/voice"

    client = Client(
        os.environ["TWILIO_ACCOUNT_SID"],
        os.environ["TWILIO_AUTH_TOKEN"],
    )
    from_number = os.environ["TWILIO_PHONE_NUMBER"].replace(" ", "")

    print(f"Calling {TARGET} from {from_number}")
    print(f"Webhook: {webhook_url}")

    call = client.calls.create(
        to=TARGET,
        from_=from_number,
        url=webhook_url,
    )
    print(f"Call SID: {call.sid}")
    print("Watch server logs for transcript output.")


if __name__ == "__main__":
    main()
