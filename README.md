# pgai -- Voice Bot for Pretty Good AI Assessment

Automated voice bot that calls Pretty Good AI's test line (+1-805-439-8008), role-plays as a patient using Amazon Nova Sonic for speech-to-speech AI, records transcripts, and uses Gemini to identify bugs in the agent's responses.

## LLM / API Stack

| Service | What it does | Model |
|---|---|---|
| **Twilio** | Makes outbound phone calls and provides a bidirectional audio WebSocket (media streams) between our bot and the phone network | N/A (telephony) |
| **Amazon Nova Sonic** (via Bedrock) | Speech-to-speech model that **is** the patient brain -- listens to the agent's audio, reasons about the scenario, and speaks back. One bidirectional stream handles STT + LLM + TTS. No separate transcription or synthesis services needed. | `amazon.nova-2-sonic-v1:0` |
| **Google Gemini** | Text-mode post-call analysis -- reads transcripts and auto-detects bugs, quality issues, and edge-case failures in the agent's responses | `gemini-3.1-flash-lite-preview` |

## Prerequisites

- Python 3.11 or 3.12 (**not** 3.13 -- `audioop` was removed)
- [uv](https://docs.astral.sh/uv/) for dependency management
- A Twilio account with a phone number
- AWS account with Bedrock model access enabled for Nova Sonic in `us-east-1`
- A Google AI Studio API key
- ngrok (or similar) to expose your local WebSocket server to Twilio

## Setup

```bash
git clone git@github.com:jack-chaudier/pgai.git
cd pgai

# Copy env and fill in your keys
cp .env.example .env
# Edit .env with your Twilio, AWS, and Google API credentials

# Install dependencies
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Getting API Keys

- **Twilio**: Sign up at twilio.com/try-twilio. Grab Account SID, Auth Token, and buy a phone number.
- **AWS Bedrock**: Create an AWS account, go to Bedrock console in us-east-1, and enable model access for `amazon.nova-2-sonic-v1:0`. Create an IAM user with Bedrock permissions.
- **Google AI**: Go to aistudio.google.com/apikey and create a key.

## How to Run

### Single call

Open three terminals:

```bash
# Terminal 1: Start the server
uvicorn src.server:app --port 8000

# Terminal 2: Expose to the internet
ngrok http 8000

# Terminal 3: Place the call (use the ngrok URL from terminal 2)
python scripts/make_call.py https://abc123.ngrok.app
```

The bot will call the PGAI test line, run the active scenario, save a transcript and WAV recording to `transcripts/`, and hang up when the conversation is done.

### Batch run (all 16 scenarios)

```bash
# Terminals 1 and 2 same as above, then:
python scripts/run_batch.py https://abc123.ngrok.app
```

This runs all 16 scenarios sequentially, waiting for each call to complete before starting the next. Each call saves a transcript, WAV recording, and per-call cost breakdown to `transcripts/`. A summary is written to `transcripts/batch-results.json`.

To run a subset: `python scripts/run_batch.py <ngrok_url> --scenarios 1,2,5`

### Post-call analysis

```bash
python -m src.analyzer
```

Sends all transcripts to Gemini for automated bug detection. Results are saved as `.analysis.json` files alongside each transcript, and consolidated into `transcripts/all-bugs.json`.

### Tests

```bash
python -m pytest tests/
```

## Project Structure

```
src/
  server.py          FastAPI app, accepts Twilio media stream WebSockets
  bridge.py          Bridges Twilio audio <-> Nova Sonic bidirectional stream
  nova_sonic.py      Amazon Nova Sonic Bedrock client
  twilio_ws.py       Twilio WebSocket protocol handler
  audio.py           Sample rate conversion (8kHz mu-law <-> 16/24kHz PCM)
  analyzer.py        Post-call transcript analysis via Gemini
scripts/
  make_call.py       Place a single call via Twilio
  run_batch.py       Run all 16 scenarios sequentially with cost tracking
scenarios/
  scenarios.json     16 patient scenario definitions
transcripts/         Saved transcripts (.json, .txt), recordings (.wav), analysis
tests/               Unit tests
ARCHITECTURE.md      System design and key decisions
BUG_REPORT.md        Consolidated bug report
```
