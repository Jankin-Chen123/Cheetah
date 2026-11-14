"""Bounded streaming ASR transport; caller owns invitation, budget and persistence."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

from websockets.asyncio.client import connect

from app.core.config import Settings


async def transcribe_stream(
    settings: Settings,
    frames: AsyncIterator[bytes],
    emit: Callable[[dict], Awaitable[None]],
):
    if settings.voice_provider == "volcengine":
        from app.integrations.voice.volcengine import transcribe

        return await transcribe(settings, frames, emit)
    if not settings.bailian_api_key or not settings.bailian_base_url:
        raise RuntimeError("REALTIME_NOT_CONFIGURED")
    parsed = urlparse(settings.bailian_base_url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(
        ".cn-beijing.maas.aliyuncs.com"
    ):
        raise RuntimeError("CONFIRMED_BEIJING_WORKSPACE_REQUIRED")
    model = "qwen3.8-omni-flash-realtime"
    async with (
        asyncio.timeout(650),
        connect(
            f"wss://{parsed.hostname}/api-ws/v1/realtime?model={model}",
            additional_headers={
                "Authorization": "Bearer " + settings.bailian_api_key.get_secret_value()
            },
            open_timeout=15,
            close_timeout=3,
            max_size=1000000,
        ) as socket,
    ):

        async def receive():
            event = json.loads(await socket.recv())
            if event.get("type") == "error":
                raise RuntimeError("STREAM_PROVIDER_ERROR")
            return event

        await receive()
        await socket.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "modalities": ["text"],
                        "turn_detection": None,
                        "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
                        "audio": {"input": {"format": {"type": "pcm", "sample_rate": 16000}}},
                    },
                }
            )
        )
        while (await receive()).get("type") != "session.updated":
            pass

        async def upload():
            size = 0
            async with asyncio.timeout(605):
                async for frame in frames:
                    if not frame or len(frame) % 2 or len(frame) > 32768:
                        raise ValueError("STREAM_PCM_FRAME_INVALID")
                    size += len(frame)
                    if size > 19200000:
                        raise ValueError("STREAM_AUDIO_DURATION_LIMIT")
                    await socket.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(frame).decode(),
                            }
                        )
                    )
                if not size:
                    raise ValueError("STREAM_AUDIO_EMPTY")
                await socket.send(json.dumps({"type": "input_audio_buffer.commit"}))

        async def consume():
            while True:
                event = await receive()
                kind = event.get("type", "")
                if kind == "conversation.item.input_audio_transcription.failed":
                    raise RuntimeError("STREAM_TRANSCRIPTION_FAILED")
                if "input_audio_transcription" not in kind:
                    continue
                if len(json.dumps(event)) > 50000:
                    raise RuntimeError("STREAM_TRANSCRIPT_LIMIT")
                if kind.endswith(".completed"):
                    text = event.get("transcript", "").strip()
                    if not text:
                        raise RuntimeError("STREAM_TRANSCRIPTION_EMPTY")
                    return {"text": text, "model": model, "source_mode": "live"}
                await emit(
                    {
                        "type": "transcript_delta",
                        "text": event.get("text", "") + event.get("stash", ""),
                    }
                )

        async with asyncio.TaskGroup() as group:
            group.create_task(upload())
            result = group.create_task(consume())
        return result.result()
