"""Test Nova Sonic threaded connection inside a uvicorn-like environment."""

import asyncio
import threading
import json
import os
import base64
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
from aws_sdk_bedrock_runtime.config import Config
from aws_sdk_bedrock_runtime.models import *
from smithy_aws_core.identity import AWSCredentialsIdentity


class C:
    async def get_identity(self, *, properties):
        return AWSCredentialsIdentity(
            access_key_id=os.environ['AWS_ACCESS_KEY'],
            secret_access_key=os.environ['AWS_SECRET_KEY'],
        )


def nova_thread(ready_event):
    async def session():
        client = BedrockRuntimeClient(config=Config(
            aws_credentials_identity_resolver=C(), region='us-east-1',
        ))
        stream = await client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id='amazon.nova-2-sonic-v1:0')
        )
        pn, cn = str(uuid.uuid4()), str(uuid.uuid4())

        async def setup():
            for evt in [
                {'event': {'sessionStart': {'inferenceConfiguration': {'maxTokens': 1024}}}},
                {'event': {'promptStart': {'promptName': pn, 'textOutputConfiguration': {'mediaType': 'text/plain'}, 'audioOutputConfiguration': {'mediaType': 'audio/lpcm', 'sampleRateHertz': 24000, 'sampleSizeBits': 16, 'channelCount': 1, 'voiceId': 'matthew'}}}},
                {'event': {'contentStart': {'promptName': pn, 'contentName': cn, 'type': 'AUDIO', 'interactive': True, 'role': 'USER', 'audioInputConfiguration': {'mediaType': 'audio/lpcm', 'sampleRateHertz': 16000, 'sampleSizeBits': 16, 'channelCount': 1}}}},
            ]:
                await stream.input_stream.send(InvokeModelWithBidirectionalStreamInputChunk(
                    value=BidirectionalInputPayloadPart(bytes_=json.dumps(evt).encode())
                ))
            silence = base64.b64encode(b'\x00' * 3200).decode()
            for _ in range(30):
                await stream.input_stream.send(InvokeModelWithBidirectionalStreamInputChunk(
                    value=BidirectionalInputPayloadPart(bytes_=json.dumps(
                        {'event': {'audioInput': {'promptName': pn, 'contentName': cn, 'content': silence}}}
                    ).encode())
                ))
                await asyncio.sleep(0.1)

        async def get_output():
            _, out = await stream.await_output()

        await asyncio.gather(setup(), get_output())
        ready_event.set()
        print("  NOVA THREAD: connected!", flush=True)

    asyncio.run(session())


async def simulate_uvicorn():
    """Simulate what happens inside a uvicorn handler."""
    print("Starting Nova thread from async context...", flush=True)
    ready = threading.Event()
    t = threading.Thread(target=nova_thread, args=(ready,), daemon=True)
    t.start()

    # Simulate doing async work while waiting
    for i in range(20):
        await asyncio.sleep(0.5)
        if ready.is_set():
            print(f"  Nova ready after {(i+1)*0.5}s", flush=True)
            break
    else:
        print("  TIMED OUT after 10s", flush=True)


if __name__ == "__main__":
    # This simulates uvicorn running an event loop
    asyncio.run(simulate_uvicorn())
