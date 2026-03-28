"""Tests for Twilio WebSocket handler and server endpoints."""

import base64
import json

from fastapi.testclient import TestClient

from src.server import app


def test_twiml_webhook_returns_valid_xml():
    client = TestClient(app)
    resp = client.post("/twilio/voice", headers={"host": "example.ngrok.io"})
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert '<Stream url="wss://example.ngrok.io/ws/twilio"' in resp.text
    assert "<Connect>" in resp.text


def test_twiml_uses_request_host():
    client = TestClient(app)
    resp = client.post("/twilio/voice", headers={"host": "abc123.ngrok.app"})
    assert "wss://abc123.ngrok.app/ws/twilio" in resp.text
