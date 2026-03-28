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


@dataclass
class NovaEvent:
    type: str  # "audio", "text", "turn_end"
    data: str = ""  # base64 audio for "audio", text content for "text"
    role: str = ""  # "USER" or "ASSISTANT" for "text" events


@dataclass
class NovaSonicSession:
    system_prompt: str
    voice_id: str = "matthew"
    model_id: str = "amazon.nova-2-sonic-v1:0"
    region: str = "us-east-1"

    _client: BedrockRuntimeClient | None = field(default=None, repr=False)
    _stream: object | None = field(default=None, repr=False)
    _output_stream: object | None = field(default=None, repr=False)
    _prompt_name: str = field(default_factory=lambda: str(uuid.uuid4()))
    _audio_content_name: str = field(default_factory=lambda: str(uuid.uuid4()))
    _audio_started: bool = field(default=False)

    async def connect(self) -> None:
        """Open bidirectional stream and send session setup events."""
        config = Config(
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            region=self.region,
        )
        self._client = BedrockRuntimeClient(config=config)

        self._stream = await self._client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )

        # Get output stream handle
        _, self._output_stream = await self._stream.await_output()

        # Send session setup in order
        await self._send_event(self._session_start_event())
        await self._send_event(self._prompt_start_event())
        await self._send_system_prompt()
        await self._start_audio_input()

    async def send_audio(self, pcm_b64: str) -> None:
        """Send a chunk of 16kHz PCM16 base64-encoded audio."""
        if not pcm_b64:
            return
        await self._send_event({
            "event": {
                "audioInput": {
                    "promptName": self._prompt_name,
                    "contentName": self._audio_content_name,
                    "content": pcm_b64,
                }
            }
        })

    async def receive_events(self) -> AsyncIterator[NovaEvent]:
        """Yield normalized events from Nova Sonic's output stream."""
        async for event in self._output_stream:
            if isinstance(event, InvokeModelWithBidirectionalStreamOutputChunk):
                if event.value.bytes_ is None:
                    continue
                data = json.loads(event.value.bytes_.decode("utf-8"))
                parsed = self._parse_output_event(data)
                if parsed is not None:
                    yield parsed

    async def close(self) -> None:
        """End the audio content, prompt, and session."""
        try:
            # Close audio content
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName": self._prompt_name,
                        "contentName": self._audio_content_name,
                    }
                }
            })
            # Close prompt
            await self._send_event({
                "event": {
                    "promptEnd": {
                        "promptName": self._prompt_name,
                    }
                }
            })
            # End session
            await self._send_event({
                "event": {
                    "sessionEnd": {}
                }
            })
        except Exception:
            pass
        finally:
            if self._stream is not None:
                try:
                    await self._stream.input_stream.close()
                except Exception:
                    pass

    # -- Internal helpers --

    async def _send_event(self, event_dict: dict) -> None:
        chunk = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(
                bytes_=json.dumps(event_dict).encode("utf-8")
            )
        )
        await self._stream.input_stream.send(chunk)

    def _session_start_event(self) -> dict:
        return {
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {
                        "maxTokens": 1024,
                        "topP": 0.9,
                        "temperature": 0.7,
                    }
                }
            }
        }

    def _prompt_start_event(self) -> dict:
        return {
            "event": {
                "promptStart": {
                    "promptName": self._prompt_name,
                    "textOutputConfiguration": {
                        "mediaType": "text/plain",
                    },
                    "audioOutputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 24000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "voiceId": self.voice_id,
                    },
                }
            }
        }

    async def _send_system_prompt(self) -> None:
        content_name = str(uuid.uuid4())
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self._prompt_name,
                    "contentName": content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "SYSTEM",
                    "textInputConfiguration": {
                        "mediaType": "text/plain",
                    },
                }
            }
        })
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName": self._prompt_name,
                    "contentName": content_name,
                    "content": self.system_prompt,
                }
            }
        })
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName": self._prompt_name,
                    "contentName": content_name,
                }
            }
        })

    async def _start_audio_input(self) -> None:
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self._prompt_name,
                    "contentName": self._audio_content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 16000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                    },
                }
            }
        })
        self._audio_started = True

    def _parse_output_event(self, data: dict) -> NovaEvent | None:
        event = data.get("event", {})

        if "audioOutput" in event:
            return NovaEvent(
                type="audio",
                data=event["audioOutput"].get("content", ""),
            )

        if "textOutput" in event:
            content = event["textOutput"].get("content", "")
            role = event["textOutput"].get("role", "")
            if content:
                return NovaEvent(type="text", data=content, role=role)

        if "contentStart" in event:
            cs = event["contentStart"]
            role = cs.get("role", "")
            ctype = cs.get("type", "")
            if role and ctype == "TEXT":
                return NovaEvent(type="text_start", role=role)

        if "completionEnd" in event:
            return NovaEvent(type="turn_end")

        return None
