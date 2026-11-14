import asyncio
import base64
import gzip
import io
import json
import struct
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.integrations.voice import volcengine
from app.integrations.voice.tts import stream_question
from app.modules.outreach.conversation_options import voice_catalog, voice_id


def settings():
    return Settings(voice_provider="volcengine", volc_speech_api_key="test-speech-key")


def response_packet(text, final=False):
    payload = gzip.compress(json.dumps({"result": {"text": text}}).encode())
    return (
        bytes([0x11, 0x93 if final else 0x91, 0x11, 0])
        + struct.pack(">iI", -1 if final else 1, len(payload))
        + payload
    )


def test_separate_credentials_and_provider_catalog(monkeypatch):
    with pytest.raises(RuntimeError, match="VOLC_SPEECH_NOT_CONFIGURED"):
        volcengine.speech_headers(
            Settings(volc_speech_api_key=None, ark_api_key="text-only"), "seed-tts-2.0"
        )
    monkeypatch.setenv("CHEETA_VOICE_PROVIDER", "volcengine")
    voices = voice_catalog(settings())
    assert len(voices) == 6
    assert voice_id(SimpleNamespace(session_data={"voice_id": "longyan_v3.1"})) == voices[0]["id"]
    with pytest.raises(ValueError, match="VOICE_NOT_SUPPORTED"):
        next(stream_question(settings(), "您好", "longyan_v3.1"))


def test_tts_yields_audio_before_completion(monkeypatch):
    audio = b"\x00\x01" * 80
    events = [
        {"code": 0, "data": base64.b64encode(audio).decode()},
        {"code": 20000000},
    ]
    response = io.BytesIO(
        b"".join(b"data: " + json.dumps(item).encode() + b"\n" for item in events)
    )

    def open_request(request, timeout):
        assert request.get_header("X-api-key") == "test-speech-key"
        assert (
            json.loads(request.data)["req_params"]["speaker"] == voice_catalog(settings())[0]["id"]
        )
        return response

    monkeypatch.setattr(volcengine, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    stream = stream_question(settings(), "您好", voice_catalog(settings())[0]["id"])
    assert next(stream) == audio
    with pytest.raises(StopIteration) as result:
        next(stream)
    assert result.value.value["pcm"] == audio
    assert result.value.value["provider"] == "volcengine"


def test_asr_protocol_and_malformed_packet():
    assert volcengine.decode_asr(response_packet("可以继续", True)) == (
        {"result": {"text": "可以继续"}},
        True,
    )
    packet = volcengine.asr_packet(2, b"\x00\x01", final=True)
    assert packet[:4] == bytes([0x11, 0x22, 1, 0])
    assert gzip.decompress(packet[8:]) == b"\x00\x01"
    for invalid in [b"", response_packet("你好")[:-1], bytes([0x10, 0x91, 0x11, 0]) + b"\0" * 8]:
        with pytest.raises(RuntimeError, match="VOLC_ASR_PACKET_INVALID"):
            volcengine.decode_asr(invalid)


def test_asr_emits_partial_text_and_final(monkeypatch):
    class Socket:
        def __init__(self):
            self.sent = []
            self.responses = iter([response_packet("可以"), response_packet("可以继续。", True)])

        async def send(self, data):
            self.sent.append(data)

        async def recv(self):
            return next(self.responses)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    socket = Socket()
    monkeypatch.setattr(volcengine, "connect", lambda *_, **__: socket)

    async def frames():
        yield b"\x00\x01" * 160

    emitted = []

    async def emit(event):
        emitted.append(event)

    result = asyncio.run(volcengine.transcribe(settings(), frames(), emit))
    assert [event["text"] for event in emitted] == ["可以", "可以继续。"]
    assert result["text"] == "可以继续。"
    assert socket.sent[-1][1] == 0x22


def test_recorded_transcription_uses_selected_speech_provider(monkeypatch):
    from app.integrations.voice.realtime import audio_roundtrip

    async def transcribe(config, frames, emit):
        assert config.voice_provider == "volcengine"
        assert b"".join([frame async for frame in frames]) == b"\x00\x01" * 2000
        return {"text": "可以继续", "provider": "volcengine"}

    monkeypatch.setattr(volcengine, "transcribe", transcribe)
    result = audio_roundtrip(settings(), b"\x00\x01" * 2000, transcription_only=True)
    assert result == {"text": "可以继续", "provider": "volcengine"}
