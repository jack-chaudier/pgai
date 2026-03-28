"""Nova Sonic bidirectional speech-to-speech client wrapper."""

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
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


class _StaticCreds:
    """Credential resolver for the Smithy SDK. Config's aws_access_key_id
    fields don't wire up a resolver automatically — we must provide one."""

    def __init__(self, access_key: str, secret_key: str, session_token: str | None = None):
        self._ak = access_key
        self._sk = secret_key
        self._token = session_token

    async def get_identity(self, *, properties):
        return AWSCredentialsIdentity(
            access_key_id=self._ak,
            secret_access_key=self._sk,
            session_token=self._token,
        )


@dataclass
class NovaEvent:
    type: str  # "audio", "text", "text_start", "turn_end"
    data: str = ""
    role: str = ""


@dataclass
class NovaSonicSession:
    system_prompt: str
    voice_id: str = "matthew"
    model_id: str = "amazon.nova-2-sonic-v1:0"
    region: str = "us-east-1"

    _stream: object | None = field(default=None, repr=False, init=False)
    _output_stream: object | None = field(default=None, repr=False, init=False)
    _prompt_name: str = field(default_factory=lambda: str(uuid.uuid4()), init=False)
    _content_name: str = field(default_factory=lambda: str(uuid.uuid4()), init=False)

    async def connect(self) -> None:
        """Open stream, send session setup, and get the output stream."""
        ak = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY", "")
        sk = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_KEY", "")
        token = os.environ.get("AWS_SESSION_TOKEN")

        client = BedrockRuntimeClient(config=Config(
            aws_credentials_identity_resolver=_StaticCreds(ak, sk, token),
            region=self.region,
        ))
        self._stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )

        # Must send events and await output concurrently — await_output()
        # blocks until the HTTP/2 response headers arrive, which requires
        # the server to have received our initial events.
        async def _setup():
            await self._send({"event": {"sessionStart": {"inferenceConfiguration": {
                "maxTokens": 1024, "topP": 0.9, "temperature": 0.7,
            }}}})
            await self._send({"event": {"promptStart": {
                "promptName": self._prompt_name,
                "textOutputConfiguration": {"mediaType": "text/plain"},
                "audioOutputConfiguration": {
                    "mediaType": "audio/lpcm", "sampleRateHertz": 24000,
                    "sampleSizeBits": 16, "channelCount": 1,
                    "voiceId": self.voice_id,
                },
            }}})
            # System prompt
            sys_name = str(uuid.uuid4())
            await self._send({"event": {"contentStart": {
                "promptName": self._prompt_name, "contentName": sys_name,
                "type": "TEXT", "interactive": False, "role": "SYSTEM",
                "textInputConfiguration": {"mediaType": "text/plain"},
            }}})
            await self._send({"event": {"textInput": {
                "promptName": self._prompt_name, "contentName": sys_name,
                "content": self.system_prompt,
            }}})
            await self._send({"event": {"contentEnd": {
                "promptName": self._prompt_name, "contentName": sys_name,
            }}})
            # Open audio input channel
            await self._send({"event": {"contentStart": {
                "promptName": self._prompt_name, "contentName": self._content_name,
                "type": "AUDIO", "interactive": True, "role": "USER",
                "audioInputConfiguration": {
                    "mediaType": "audio/lpcm", "sampleRateHertz": 16000,
                    "sampleSizeBits": 16, "channelCount": 1,
                },
            }}})
            # Send silence to keep data flowing — await_output() only resolves
            # once the HTTP/2 response headers arrive, which needs sustained
            # data on the wire.
            silence_b64 = base64.b64encode(b"\x00" * 3200).decode("ascii")
            for _ in range(20):
                await self._send({"event": {"audioInput": {
                    "promptName": self._prompt_name,
                    "contentName": self._content_name,
                    "content": silence_b64,
                }}})
                await asyncio.sleep(0.1)

        async def _get_output():
            _, self._output_stream = await self._stream.await_output()

        await asyncio.gather(_setup(), _get_output())

    async def send_audio(self, pcm_b64: str) -> None:
        """Send 16kHz PCM16 base64 audio chunk to Nova Sonic."""
        if not pcm_b64:
            return
        await self._send({"event": {"audioInput": {
            "promptName": self._prompt_name,
            "contentName": self._content_name,
            "content": pcm_b64,
        }}})

    async def receive_events(self) -> AsyncIterator[NovaEvent]:
        """Yield parsed events from the output stream."""
        async for event in self._output_stream:
            if not isinstance(event, InvokeModelWithBidirectionalStreamOutputChunk):
                continue
            if event.value.bytes_ is None:
                continue
            evt = json.loads(event.value.bytes_.decode("utf-8")).get("event", {})
            parsed = self._parse(evt)
            if parsed is not None:
                yield parsed

    async def close(self) -> None:
        """Cleanly end the session."""
        try:
            await self._send({"event": {"contentEnd": {
                "promptName": self._prompt_name,
                "contentName": self._content_name,
            }}})
            await self._send({"event": {"promptEnd": {
                "promptName": self._prompt_name,
            }}})
            await self._send({"event": {"sessionEnd": {}}})
        except Exception:
            pass
        if self._stream:
            try:
                await self._stream.input_stream.close()
            except Exception:
                pass

    async def _send(self, event_dict: dict) -> None:
        await self._stream.input_stream.send(
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
