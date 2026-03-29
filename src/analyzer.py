"""Post-call transcript analysis using Gemini 3.1 Flash Lite."""

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()
log = logging.getLogger(__name__)

MODEL = "gemini-3.1-flash-lite-preview"

ANALYSIS_PROMPT = """\
You are a QA analyst reviewing a phone call transcript between a patient (PATIENT) \
and a medical office AI receptionist (AGENT) at Pivot Point Orthopedics.

Analyze the transcript for bugs, quality issues, and edge-case failures in the \
AI receptionist's (USER's) responses. Focus on:

1. **Factual errors** — wrong information, contradictions, impossible claims
2. **Logic failures** — booking errors, wrong appointment types, ignoring patient context
3. **Safety issues** — failing to recommend urgent care for emergencies, bad medical advice
4. **UX problems** — asking for info already provided, confusing flow, excessive repetition
5. **System errors** — booking failures, "system issue" messages, crashes

For each issue found, provide:
- **Bug**: One-line summary
- **Severity**: Critical / High / Medium / Low
- **Details**: What happened, why it's a problem, what should have happened instead
- **Quote**: The relevant part of the transcript

Also note if the call went well — not every call has bugs.

Output as JSON array:
```json
[
  {
    "bug": "summary",
    "severity": "High",
    "details": "explanation",
    "quote": "relevant transcript text"
  }
]
```

If no bugs found, return an empty array: []

TRANSCRIPT:
{transcript}
"""


def analyze_transcript(transcript: list[dict]) -> list[dict]:
    """Analyze a transcript and return a list of bugs found."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # Format transcript as readable text
    text = "\n".join(f"[{e['role']}] {e['content']}" for e in transcript)
    prompt = ANALYSIS_PROMPT.replace("{transcript}", text)

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    # Parse JSON from response
    raw = response.text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]
        elif "```" in raw:
            raw = raw[:raw.rfind("```")]
    raw = raw.strip()

    try:
        bugs = json.loads(raw)
        return bugs if isinstance(bugs, list) else []
    except json.JSONDecodeError:
        log.warning("Failed to parse Gemini response as JSON: %s", raw[:200])
        return []


def analyze_file(transcript_path: str) -> list[dict]:
    """Analyze a transcript JSON file and save analysis alongside it."""
    path = Path(transcript_path)
    with open(path) as f:
        data = json.load(f)
    # Support both old format (flat list) and new format (with metadata)
    transcript = data.get("transcript", data) if isinstance(data, dict) else data

    bugs = analyze_transcript(transcript)

    # Save analysis
    analysis_path = path.with_suffix(".analysis.json")
    with open(analysis_path, "w") as f:
        json.dump(bugs, f, indent=2)
    log.info("Analysis saved to %s (%d bugs found)", analysis_path, len(bugs))

    return bugs


def analyze_all():
    """Analyze all transcript JSON files in transcripts/."""
    transcript_dir = Path("transcripts")
    all_bugs = []

    for path in sorted(transcript_dir.glob("*.json")):
        if ".analysis." in path.name or path.name in ("all-bugs.json", "batch-results.json"):
            continue
        # Skip if already analyzed
        analysis_path = path.with_suffix(".analysis.json")
        if analysis_path.exists():
            with open(analysis_path) as f:
                bugs = json.load(f)
            print(f"Skipping {path.name} (already analyzed, {len(bugs)} bugs)")
            all_bugs.extend({"file": path.name, **bug} for bug in bugs)
            continue
        print(f"Analyzing {path.name}...", end=" ", flush=True)
        bugs = analyze_file(str(path))
        print(f"{len(bugs)} bugs found")
        all_bugs.extend({"file": path.name, **bug} for bug in bugs)
        time.sleep(5)  # rate limit: 15 req/min

    # Save combined report
    report_path = transcript_dir / "all-bugs.json"
    with open(report_path, "w") as f:
        json.dump(all_bugs, f, indent=2)
    print(f"\nTotal: {len(all_bugs)} bugs across all calls")
    print(f"Saved to {report_path}")

    return all_bugs


if __name__ == "__main__":
    analyze_all()
