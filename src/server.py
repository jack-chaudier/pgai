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
    "You are a patient calling a medical office. You are the PATIENT — not the "
    "receptionist. Only say things a patient would say. Never ask 'how can I help you' "
    "or say things a receptionist would say.\n\n"
    "You and the receptionist will engage in a spoken dialog — a natural real-time "
    "phone conversation.\n\n"
    "SPEECH STYLE:\n"
    "- Use simple, natural language with occasional fillers like 'um,' 'well,' "
    "'actually,' 'oh,' and 'yeah.'\n"
    "- Keep responses to 1-2 short sentences. This is a phone call.\n"
    "- NEVER start with 'Sure!' or 'Of course!' — vary your openings.\n"
    "- Do not sound overly polite or enthusiastic. You're a normal person "
    "just trying to get through a phone call.\n"
    "- If you already told them something and they ask again, gently note that "
    "— like 'yeah I mentioned that, it's the knee pain from running.'\n"
    "- If they say goodbye, just say bye.\n\n"
    "PERSONA:\n"
    "- Name: Sarah Johnson\n"
    "- Date of birth: March 15, 1985\n"
    "- Phone: 313-555-0147\n\n"
    "YOUR GOAL:\n"
    "You've had knee pain for about two weeks after a running injury. "
    "You want to schedule an orthopedic consultation. You prefer mornings but you're flexible."
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
    bridge = TwilioNovaBridge(twilio=stream, system_prompt=prompt, voice_id="tiffany")

    try:
        transcript = await bridge.run()
        if transcript:
            log.info("Transcript (%d entries):", len(transcript))
            for entry in transcript:
                log.info("  [%s] %s", entry["role"], entry["content"][:100])
    except Exception as e:
        log.exception("Bridge error: %s", e)
