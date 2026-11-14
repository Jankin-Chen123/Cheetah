import pytest

from app.core.config import Settings
from app.integrations.voice.realtime import audio_roundtrip


@pytest.mark.parametrize("pcm", [b"", b"x", b"x" * 320002])
def test_audio_limits_reject_before_network(pcm):
    with pytest.raises(ValueError, match="MAX_10_SECONDS"):
        audio_roundtrip(Settings(), pcm)


def test_audio_requires_explicit_local_configuration():
    with pytest.raises(RuntimeError, match="NOT_CONFIGURED"):
        audio_roundtrip(Settings(bailian_api_key=None), b"\x00\x00")


@pytest.mark.parametrize("text", ["", " ", "x" * 1001])
def test_question_speech_limits_before_network(text):
    with pytest.raises(ValueError, match="SPEECH_TEXT_INVALID"):
        audio_roundtrip(Settings(), b"", speak_text=text)


def test_transcription_only_never_requests_model_reply(monkeypatch):
    import json

    events = iter(
        [
            {"type": "session.created"},
            {"type": "session.updated"},
            {"type": "input_audio_buffer.committed"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "虚构回答",
            },
        ]
    )
    sent = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def recv(self, **kwargs):
            return json.dumps(next(events))

        def send(self, value):
            sent.append(json.loads(value))

    monkeypatch.setattr("app.integrations.voice.realtime.connect", lambda *args, **kw: Connection())
    result = audio_roundtrip(
        Settings(
            bailian_api_key="fixture-key",
            bailian_base_url="https://fixture.cn-beijing.maas.aliyuncs.com",
        ),
        b"\x00\x00",
        transcription_only=True,
    )
    assert result["text"] == "虚构回答"
    assert all(event["type"] != "response.create" for event in sent)
