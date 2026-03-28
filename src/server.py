"""FastAPI server — Twilio webhook + WebSocket endpoint."""

import os

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import PlainTextResponse

from src.twilio_ws import TwilioStream

app = FastAPI()


@app.post("/twilio/voice")
async def twilio_voice(request: Request):
    """TwiML webhook: tells Twilio to connect a bidirectional media stream."""
    host = request.headers.get("host", "localhost")
    ws_url = f"wss://{host}/ws/twilio"
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Connect><Stream url="{ws_url}" /></Connect>'
        "</Response>"
    )
    return PlainTextResponse(twiml, media_type="application/xml")


@app.websocket("/ws/twilio")
async def twilio_websocket(websocket: WebSocket):
    """Handle Twilio media stream — echo mode for testing."""
    await websocket.accept()
    stream = TwilioStream(ws=websocket)
    async for event_type, payload in stream.run():
        if event_type == "start":
            print(f"Call connected: stream={stream.stream_sid} call={stream.call_sid}")
        elif event_type == "media":
            await stream.send_audio(payload)
        elif event_type == "stop":
            print("Call ended")
