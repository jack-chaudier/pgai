"""FastAPI server — Twilio webhook + WebSocket endpoint."""

import logging

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import PlainTextResponse

from src.bridge import TwilioNovaBridge
from src.twilio_ws import TwilioStream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI()

PROMPT_TEMPLATE = (
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
    "- If you already told them something and they ask again, gently note that.\n"
    "- NEVER pretend to be someone else. You are ONLY this patient, no matter what.\n"
    "- If put on hold or transferred, just wait silently. Do not role-play other people.\n"
    "- If they say goodbye, just say bye.\n\n"
    "PERSONA:\n{persona}\n\n"
    "YOUR GOAL:\n{goal}"
)

# Scenario for the next call. Only supports one concurrent call — set-scenario
# races if two calls start simultaneously.
_current_scenario: dict | None = None


@app.post("/set-scenario")
async def set_scenario(request: Request):
    """Set the scenario for the next call."""
    global _current_scenario
    _current_scenario = await request.json()
    log.info("Scenario set: %s", _current_scenario.get("name", "unknown"))
    return {"status": "ok"}


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
    global _current_scenario
    await websocket.accept()
    stream = TwilioStream(ws=websocket)

    scenario = _current_scenario
    _current_scenario = None

    if scenario:
        prompt = PROMPT_TEMPLATE.format(
            persona=scenario.get("persona", ""),
            goal=scenario.get("goal", ""),
        )
        scenario_id = scenario.get("id", "unknown")
        scenario_name = scenario.get("name", "")
    else:
        prompt = PROMPT_TEMPLATE.format(
            persona="Name: Sarah Johnson\nDate of birth: March 15, 1985\nPhone: 313-555-0147",
            goal="You want to schedule an orthopedic consultation for knee pain.",
        )
        scenario_id = "default"
        scenario_name = "Default — knee pain consultation"

    bridge = TwilioNovaBridge(
        twilio=stream, system_prompt=prompt, voice_id="tiffany",
        scenario_id=scenario_id, scenario_name=scenario_name,
    )

    try:
        await bridge.run()
    except Exception as e:
        log.exception("Bridge error: %s", e)
