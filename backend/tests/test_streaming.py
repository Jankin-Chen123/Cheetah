import asyncio
import json

from app.core.config import Settings
from app.integrations.voice.streaming import transcribe_stream


def test_streaming_text_and_stash_are_replacement_snapshot(monkeypatch):
    sent = []
    events = iter(
        [
            {"type": "session.created"},
            {"type": "session.updated"},
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "text": "",
                "stash": "虚构",
            },
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "text": "虚构",
                "stash": "回答",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "虚构回答",
            },
        ]
    )

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, value):
            sent.append(json.loads(value))

        async def recv(self):
            await asyncio.sleep(0)
            return json.dumps(next(events))

    monkeypatch.setattr("app.integrations.voice.streaming.connect", lambda *args, **kw: Socket())

    async def check():
        async def frames():
            yield b"\x00\x00"

        deltas = []

        async def emit(event):
            deltas.append(event["text"])

        result = await transcribe_stream(
            Settings(
                bailian_api_key="fixture",
                bailian_base_url="https://fixture.cn-beijing.maas.aliyuncs.com",
            ),
            frames(),
            emit,
        )
        assert deltas == ["虚构", "虚构回答"]
        assert result["text"] == "虚构回答"
        assert all(item["type"] != "response.create" for item in sent)

    asyncio.run(check())
