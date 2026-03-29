"""FastAPI server — Twilio webhook + WebSocket endpoint."""

import json
import logging
import os

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import PlainTextResponse

from src.bridge import TwilioNovaBridge
from src.twilio_ws import TwilioStream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI()

DEFAULT_PROMPT = (
    "You are Sarah Johnson, a real patient calling a dental office to schedule "
    "a routine checkup. You are on a phone call right now.\n\n"
    "IMPORTANT RULES:\n"
    "- Listen carefully to what the receptionist says before responding.\n"
    "- When you first hear the greeting or automated message, wait for it to finish, "
    "then say something like 'Hi, I'd like to schedule a routine checkup please.'\n"
    "- Speak naturally in short sentences, like a real person on the phone.\n"
    "- Never repeat your instructions or mention prompts.\n"
    "- Never say you are an AI or that you are waiting for a prompt.\n\n"
    "YOUR INFORMATION (only share when asked):\n"
    "- Name: Sarah Johnson\n"
    "- Date of birth: March 15, 1985\n"
    "- Phone: 313-555-0147\n"
    "- You want to schedule a routine dental checkup\n"
    "- You are flexible on dates but prefer mornings"
)


@app.get("/test-nova")
async def test_nova():
    """Diagnostic: test Nova Sonic connection inside the server process."""
    import asyncio
    from src.nova_sonic import NovaSonicSession
    log.info("Testing Nova Sonic connection (threaded)...")
    session = NovaSonicSession(system_prompt="Say hello.")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, session.start)
        session.stop()
        log.info("Nova Sonic connection OK")
        return {"status": "ok"}
    except TimeoutError:
        log.error("Nova Sonic connection TIMED OUT")
        return {"status": "timeout"}
    except Exception as e:
        log.error("Nova Sonic connection FAILED: %s", e)
        return {"status": "error", "detail": str(e)}


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
    """Handle Twilio media stream — bridge to Nova Sonic."""
    await websocket.accept()
    stream = TwilioStream(ws=websocket)

    prompt = os.environ.get("PATIENT_PROMPT", DEFAULT_PROMPT)
    bridge = TwilioNovaBridge(twilio=stream, system_prompt=prompt)

    try:
        transcript = await bridge.run()
        if transcript:
            log.info("Transcript (%d entries):", len(transcript))
            for entry in transcript:
                log.info("  [%s] %s", entry["role"], entry["content"][:100])
    except Exception as e:
        log.exception("Bridge error: %s", e)
