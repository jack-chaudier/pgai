"""Tests for Twilio WebSocket handler and server endpoints."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from src.server import app


def test_twiml_webhook_returns_valid_xml():
    client = TestClient(app)
    resp = client.post("/twilio/voice", headers={"host": "example.ngrok.io"})
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert '<Stream url="wss://example.ngrok.io/ws/twilio"' in resp.text
    assert "<Connect>" in resp.text


def test_websocket_echo():
    """Send synthetic Twilio messages, verify audio is echoed back."""
    client = TestClient(app)
    with client.websocket_connect("/ws/twilio") as ws:
        # Send connected event
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))

        # Send start event
        ws.send_text(json.dumps({
            "event": "start",
            "start": {
                "streamSid": "MZ123",
                "callSid": "CA456",
                "accountSid": "AC789",
                "tracks": ["inbound"],
                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            },
            "streamSid": "MZ123",
        }))

        # Send a media event
        audio_b64 = base64.b64encode(b"\xff" * 160).decode()
        ws.send_text(json.dumps({
            "event": "media",
            "media": {"track": "inbound", "payload": audio_b64, "chunk": "1", "timestamp": "0"},
            "streamSid": "MZ123",
        }))

        # Read back the echoed audio
        resp = json.loads(ws.receive_text())
        assert resp["event"] == "media"
        assert resp["streamSid"] == "MZ123"
        assert resp["media"]["payload"] == audio_b64

        # Send stop
        ws.send_text(json.dumps({
            "event": "stop",
            "stop": {"accountSid": "AC789", "callSid": "CA456"},
            "streamSid": "MZ123",
        }))
