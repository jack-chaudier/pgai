# pgai — Voice Bot for Pretty Good AI Assessment

Automated voice bot that calls Pretty Good AI's test line, simulates patient conversations with their medical office AI agent, records transcripts, and identifies bugs.

## LLM / API Stack

| Service | What it does | Model |
|---|---|---|
| **Twilio** | Makes outbound phone calls and provides a bidirectional audio WebSocket (media streams) between our bot and the phone network | N/A (telephony) |
| **Amazon Nova Sonic** (via Bedrock) | Speech-to-speech model that **is** the patient brain — listens to the agent's audio, reasons about the scenario, and speaks back. One bidirectional stream handles STT + LLM + TTS. No separate transcription or synthesis services needed. | `amazon.nova-2-sonic-v1:0` |
| **Google Gemini 2.5 Flash** | Text-mode post-call analysis — reads transcripts and auto-detects bugs, quality issues, and edge-case failures in the agent's responses | `gemini-2.5-flash-preview-05-20` |

## Prerequisites

- Python 3.11 or 3.12 (**not** 3.13 — `audioop` was removed)
- [uv](https://docs.astral.sh/uv/) for dependency management
- A Twilio account with a phone number
- AWS account with Bedrock model access enabled for Nova Sonic in `us-east-1`
- A Google AI Studio API key
- ngrok (or similar) to expose your local WebSocket server to Twilio

## Setup

```bash
# Clone
git clone git@github.com:jack-chaudier/pgai.git
cd pgai

# Copy env and fill in your keys
cp .env.example .env

# Install dependencies
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Getting API Keys

- **Twilio**: Sign up at twilio.com/try-twilio. Grab Account SID, Auth Token, and buy a phone number.
- **AWS Bedrock**: Create an AWS account, go to Bedrock console in us-east-1, and enable model access for `amazon.nova-2-sonic-v1:0`. Create an IAM user with Bedrock permissions.
- **Google AI**: Go to aistudio.google.com/apikey and create a key.

## Usage

See `ARCHITECTURE.md` for how the system works.

```bash
# Run the voice bot (details TBD)
python -m src.main
```

## Project Structure

```
src/           — Application code
scenarios/     — Patient scenario definitions
transcripts/   — Recorded call transcripts (both sides)
analysis/      — Post-call bug analysis output
scripts/       — Helper scripts
```

## Deliverables

- [x] Working voice bot code
- [ ] ARCHITECTURE.md
- [ ] BUG_REPORT.md
- [ ] 10+ call transcripts
- [ ] Loom walkthrough
