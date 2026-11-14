"""Volcengine speech 2.0: streaming PCM TTS and real-time binary ASR."""

import asyncio
import base64
import gzip
import json
import struct
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import uuid4

from websockets.asyncio.client import connect

from app.integrations.bailian import NoRedirect


def speech_headers(settings, resource):
    if not settings.volc_speech_api_key:
        raise RuntimeError("VOLC_SPEECH_NOT_CONFIGURED")
    return {
        "X-Api-Key": settings.volc_speech_api_key.get_secret_value(),
        "X-Api-Resource-Id": resource,
        "X-Api-Request-Id": str(uuid4()),
    }


def stream_tts(settings, text, voice):
    if not text.strip() or len(text) > 1000:
        raise ValueError("SPEECH_TEXT_INVALID")
    resource = (
        settings.volc_custom_voice_resource_id
        if voice == settings.tts_custom_voice_id
        else settings.volc_tts_resource_id
    )
    headers = {**speech_headers(settings, resource), "Content-Type": "application/json"}
    body = {
        "user": {"uid": "cheetah-interview"},
        "req_params": {
            "text": text,
            "speaker": voice,
            "audio_params": {"format": "pcm", "sample_rate": 24000},
        },
    }
    request = Request(
        "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        headers=headers,
        data=json.dumps(body).encode(),
        method="POST",
    )
    chunks = []
    size = 0
    first = None
    began = time.monotonic()
    completed = False
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            while time.monotonic() - began < 45:
                line = response.readline(2000000)
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith(b"data:"):
                    line = line[5:].strip()
                event = json.loads(line)
                code = event.get("code", 0)
                if code not in (0, 20000000):
                    raise RuntimeError("VOLC_TTS_PROVIDER_ERROR")
                if event.get("data"):
                    chunk = base64.b64decode(event["data"], validate=True)
                    size += len(chunk)
                    if size > 24000 * 2 * 120:
                        raise RuntimeError("TTS_OUTPUT_LIMIT")
                    if first is None:
                        first = round((time.monotonic() - began) * 1000)
                    chunks.append(chunk)
                    yield chunk
                if code == 20000000:
                    completed = True
                    break
    except HTTPError as error:
        raise RuntimeError(f"VOLC_TTS_HTTP_{error.code}") from None
    except (URLError, TimeoutError, ValueError, TypeError):
        raise RuntimeError("VOLC_TTS_UNAVAILABLE") from None
    if not completed or not size:
        raise RuntimeError("VOLC_TTS_INCOMPLETE")
    return {
        "pcm": b"".join(chunks),
        "sample_rate": 24000,
        "model": resource,
        "voice": voice,
        "source_mode": "live",
        "provider": "volcengine",
        "telephone_line": False,
        "timings": {"first_audio_ms": first, "total_ms": round((time.monotonic() - began) * 1000)},
    }


def asr_packet(message_type, payload, *, final=False, json_payload=False):
    compressed = gzip.compress(payload)
    header = bytes(
        [0x11, message_type << 4 | (2 if final else 0), (0x10 if json_payload else 0) | 1, 0]
    )
    return header + struct.pack(">I", len(compressed)) + compressed


def decode_asr(packet):
    if not isinstance(packet, bytes) or len(packet) < 8 or len(packet) > 1000000:
        raise RuntimeError("VOLC_ASR_PACKET_INVALID")
    offset = (packet[0] & 15) * 4
    if packet[0] >> 4 != 1 or offset < 4 or packet[2] >> 4 != 1:
        raise RuntimeError("VOLC_ASR_PACKET_INVALID")
    kind, flags, compression = packet[1] >> 4, packet[1] & 15, packet[2] & 15
    if kind == 15:
        raise RuntimeError("VOLC_ASR_PROVIDER_ERROR")
    if kind != 9:
        raise RuntimeError("VOLC_ASR_PACKET_UNEXPECTED")
    if flags & 1:
        offset += 4
    if flags & 4:
        offset += 4
    if offset + 4 > len(packet):
        raise RuntimeError("VOLC_ASR_PACKET_INVALID")
    size = struct.unpack(">I", packet[offset : offset + 4])[0]
    payload = packet[offset + 4 :]
    if len(payload) != size:
        raise RuntimeError("VOLC_ASR_PACKET_INVALID")
    if compression == 1:
        import zlib

        unpacker = zlib.decompressobj(31)
        payload = unpacker.decompress(payload, 1000001)
        if len(payload) > 1000000 or unpacker.unconsumed_tail:
            raise RuntimeError("VOLC_ASR_RESULT_LIMIT")
        if not unpacker.eof or unpacker.unused_data:
            raise RuntimeError("VOLC_ASR_PACKET_INVALID")
    elif compression != 0:
        raise RuntimeError("VOLC_ASR_COMPRESSION_INVALID")
    return json.loads(payload), bool(flags & 2)


async def transcribe(settings, frames, emit):
    headers = speech_headers(settings, settings.volc_asr_resource_id)
    began = time.monotonic()
    first = None
    config = {
        "user": {"uid": "cheetah-interview"},
        "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
            "enable_nonstream": False,
        },
    }
    async with (
        asyncio.timeout(650),
        connect(
            "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
            additional_headers=headers,
            open_timeout=12,
            close_timeout=2,
            max_size=1000000,
        ) as socket,
    ):
        await socket.send(asr_packet(1, json.dumps(config).encode(), json_payload=True))
        latest = ""

        async def upload():
            size = 0
            async for frame in frames:
                if not frame or len(frame) % 2 or len(frame) > 32768:
                    raise ValueError("STREAM_PCM_FRAME_INVALID")
                size += len(frame)
                if size > 19200000:
                    raise RuntimeError("STREAM_AUDIO_DURATION_LIMIT")
                await socket.send(asr_packet(2, frame))
            if not size:
                raise RuntimeError("STREAM_AUDIO_EMPTY")
            await socket.send(asr_packet(2, b"", final=True))

        async def consume():
            nonlocal latest, first
            while True:
                data, final = decode_asr(await socket.recv())
                if data.get("code", 0) not in (0, 20000000):
                    raise RuntimeError("VOLC_ASR_PROVIDER_ERROR")
                result = data.get("result", data.get("payload_msg", {}).get("result", {}))
                if isinstance(result, list):
                    result = result[-1] if result else {}
                text = result.get("text", "").strip()
                if text and text != latest:
                    latest = text
                    if first is None:
                        first = round((time.monotonic() - began) * 1000)
                    await emit({"type": "transcript_delta", "text": text})
                if final or data.get("is_last_package"):
                    if not latest:
                        raise RuntimeError("STREAM_TRANSCRIPTION_EMPTY")
                    return {
                        "text": latest,
                        "model": "doubao-streaming-asr-2.0",
                        "provider": "volcengine",
                        "source_mode": "live",
                        "timings": {
                            "first_text_ms": first,
                            "total_ms": round((time.monotonic() - began) * 1000),
                        },
                    }

        async with asyncio.TaskGroup() as group:
            group.create_task(upload())
            receiver = group.create_task(consume())
        return receiver.result()
