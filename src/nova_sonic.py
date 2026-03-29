"""Nova Sonic bidirectional speech-to-speech client wrapper.

The awscrt HTTP/2 client doesn't work inside uvicorn's event loop,
so we run the Bedrock session in a separate thread with its own loop
and communicate via thread-safe queues.
"""

import asyncio
import base64
import json
import logging
import os
import queue
import threading
import uuid
from dataclasses import dataclass, field

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
from aws_sdk_bedrock_runtime.config import Config
from aws_sdk_bedrock_runtime.models import (
    BidirectionalInputPayloadPart,
    InvokeModelWithBidirectionalStreamInputChunk,
    InvokeModelWithBidirectionalStreamOperationInput,
    InvokeModelWithBidirectionalStreamOutputChunk,
)
from smithy_aws_core.identity import AWSCredentialsIdentity

log = logging.getLogger(__name__)

SENTINEL = object()  # unique sentinel to signal shutdown


class _StaticCreds:
    def __init__(self, access_key: str, secret_key: str, session_token: str | None = None):
        self._ak, self._sk, self._token = access_key, secret_key, session_token

    async def get_identity(self, *, properties):
        return AWSCredentialsIdentity(
            access_key_id=self._ak, secret_access_key=self._sk, session_token=self._token,
        )


def _make_client(region: str = "us-east-1") -> BedrockRuntimeClient:
    """Create the Bedrock client. Must be called before uvicorn starts
    (awscrt's HTTP/2 client breaks if initialized inside a running server)."""
    ak = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY", "")
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_KEY", "")
    token = os.environ.get("AWS_SESSION_TOKEN")
    return BedrockRuntimeClient(config=Config(
        aws_credentials_identity_resolver=_StaticCreds(ak, sk, token),
        region=region,
    ))


# Pre-create at import time so awscrt initializes before uvicorn's event loop
from dotenv import load_dotenv
load_dotenv()
_CLIENT = _make_client()


@dataclass
class NovaEvent:
    type: str  # "audio", "text", "text_start", "turn_end"
    data: str = ""
    role: str = ""


class NovaSonicSession:
    """Runs Nova Sonic in a background thread with its own event loop."""

    def __init__(self, system_prompt: str, voice_id: str = "matthew",
                 model_id: str = "amazon.nova-2-sonic-v1:0", region: str = "us-east-1"):
        self.system_prompt = system_prompt
        self.voice_id = voice_id
        self.model_id = model_id
        self.region = region

        # Thread-safe queues for audio/events between uvicorn and nova thread
        self._inbound: queue.Queue[str | None] = queue.Queue(maxsize=500)
        self._outbound: queue.Queue[NovaEvent | None] = queue.Queue(maxsize=500)

        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._prompt_name = str(uuid.uuid4())
        self._content_name = str(uuid.uuid4())

    def start(self) -> None:
        """Start the Nova Sonic thread. Call from the main (uvicorn) thread."""
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=20):
            raise TimeoutError("Nova Sonic failed to connect within 20s")
        log.info("Nova Sonic thread ready")

    def send_audio(self, pcm_b64: str) -> None:
        """Send audio to Nova (called from uvicorn thread). Non-blocking."""
        try:
            self._inbound.put_nowait(pcm_b64)
        except queue.Full:
            pass  # drop if queue is full

    def get_event(self, timeout: float = 0.01) -> NovaEvent | None:
        """Get next event from Nova (called from uvicorn thread)."""
        try:
            return self._outbound.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        """Signal the Nova thread to shut down."""
        self._inbound.put(SENTINEL)

    def _run_thread(self) -> None:
        """Entry point for the background thread — runs its own event loop."""
        try:
            asyncio.run(self._session_loop())
        except Exception:
            log.exception("Nova Sonic thread crashed")
        finally:
            self._outbound.put(SENTINEL)

    async def _session_loop(self) -> None:
        stream = await _CLIENT.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )

        async def _setup():
            await self._send(stream, {"event": {"sessionStart": {
                "inferenceConfiguration": {
                    "maxTokens": 1024, "topP": 0.9, "temperature": 0.7,
                },
                "turnDetectionConfiguration": {
                    "endpointingSensitivity": "LOW",
                },
            }}})
            await self._send(stream, {"event": {"promptStart": {
                "promptName": self._prompt_name,
                "textOutputConfiguration": {"mediaType": "text/plain"},
                "audioOutputConfiguration": {
                    "mediaType": "audio/lpcm", "sampleRateHertz": 24000,
                    "sampleSizeBits": 16, "channelCount": 1,
                    "voiceId": self.voice_id, "encoding": "base64",
                    "audioType": "SPEECH",
                },
            }}})
            sys_name = str(uuid.uuid4())
            await self._send(stream, {"event": {"contentStart": {
                "promptName": self._prompt_name, "contentName": sys_name,
                "type": "TEXT", "interactive": False, "role": "SYSTEM",
                "textInputConfiguration": {"mediaType": "text/plain"},
            }}})
            await self._send(stream, {"event": {"textInput": {
                "promptName": self._prompt_name, "contentName": sys_name,
                "content": self.system_prompt,
            }}})
            await self._send(stream, {"event": {"contentEnd": {
                "promptName": self._prompt_name, "contentName": sys_name,
            }}})
            await self._send(stream, {"event": {"contentStart": {
                "promptName": self._prompt_name, "contentName": self._content_name,
                "type": "AUDIO", "interactive": True, "role": "USER",
                "audioInputConfiguration": {
                    "mediaType": "audio/lpcm", "sampleRateHertz": 16000,
                    "sampleSizeBits": 16, "channelCount": 1,
                    "encoding": "base64", "audioType": "SPEECH",
                },
            }}})
            # Keep sending silence until output is ready
            silence_b64 = base64.b64encode(b"\x00" * 3200).decode("ascii")
            for _ in range(30):
                await self._send(stream, {"event": {"audioInput": {
                    "promptName": self._prompt_name,
                    "contentName": self._content_name,
                    "content": silence_b64,
                }}})
                await asyncio.sleep(0.1)

        async def _get_output():
            _, output_stream = await stream.await_output()
            return output_stream

        results = await asyncio.gather(_setup(), _get_output())
        output_stream = results[1]
        self._ready.set()
        log.info("Nova Sonic session established")

        # Run send and receive concurrently
        await asyncio.gather(
            self._send_loop(stream),
            self._recv_loop(output_stream),
        )

    async def _send_loop(self, stream) -> None:
        """Read audio from inbound queue and send to Nova."""
        loop = asyncio.get_event_loop()
        while True:
            pcm_b64 = await loop.run_in_executor(None, self._inbound.get)
            if pcm_b64 is SENTINEL:
                return
            await self._send(stream, {"event": {"audioInput": {
                "promptName": self._prompt_name,
                "contentName": self._content_name,
                "content": pcm_b64,
            }}})

    async def _recv_loop(self, output_stream) -> None:
        """Read events from Nova and put them in the outbound queue."""
        event_count = 0
        async for event in output_stream:
            if not isinstance(event, InvokeModelWithBidirectionalStreamOutputChunk):
                continue
            if event.value.bytes_ is None:
                continue
            evt = json.loads(event.value.bytes_.decode("utf-8")).get("event", {})
            event_count += 1
            parsed = self._parse(evt)
            if parsed is not None:
                try:
                    self._outbound.put_nowait(parsed)
                except queue.Full:
                    pass
        log.info("Nova recv loop ended after %d events", event_count)

    @staticmethod
    async def _send(stream, event_dict: dict) -> None:
        await stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(
                    bytes_=json.dumps(event_dict).encode("utf-8")
                )
            )
        )

    @staticmethod
    def _parse(evt: dict) -> NovaEvent | None:
        if "audioOutput" in evt:
            return NovaEvent(type="audio", data=evt["audioOutput"].get("content", ""))
        if "textOutput" in evt:
            content = evt["textOutput"].get("content", "")
            if content:
                return NovaEvent(type="text", data=content, role=evt["textOutput"].get("role", ""))
        if "contentStart" in evt:
            cs = evt["contentStart"]
            if cs.get("type") == "TEXT" and cs.get("role"):
                return NovaEvent(type="text_start", role=cs["role"])
        if "completionEnd" in evt:
            return NovaEvent(type="turn_end")
        return None
