import json

import pytest

from app.core.config import Settings
from app.integrations.voice.tts import synthesize_question


@pytest.mark.parametrize("failure", [False, True])
def test_tts_waits_for_started_and_bounds_task_identity(monkeypatch, failure):
    sent = []

    class Socket:
        index = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, value):
            sent.append(json.loads(value))

        def recv(self, **kwargs):
            self.index += 1
            task_id = sent[0]["header"]["task_id"]
            if self.index == 1:
                assert len(sent) == 1
                return json.dumps(
                    {
                        "header": {
                            "task_id": "wrong" if failure else task_id,
                            "event": "task-started",
                        }
                    }
                )
            if self.index == 2:
                assert [x["header"]["action"] for x in sent] == [
                    "run-task",
                    "continue-task",
                    "finish-task",
                ]
                assert sent[1]["payload"]["input"]["text"] == "虚构问题？"
                return b"\x00\x00"
            return json.dumps({"header": {"task_id": task_id, "event": "task-finished"}})

    monkeypatch.setattr("app.integrations.voice.tts.connect", lambda *a, **kw: Socket())
    settings = Settings(
        bailian_api_key="fixture", bailian_base_url="https://fixture.cn-beijing.maas.aliyuncs.com"
    )
    if failure:
        with pytest.raises(RuntimeError, match="TASK_MISMATCH"):
            synthesize_question(settings, "虚构问题？")
    else:
        assert synthesize_question(settings, "虚构问题？")["pcm"] == b"\x00\x00"


def test_stream_yields_audio_before_task_finished(monkeypatch):
    from app.integrations.voice.tts import stream_question

    sent = []
    consumed = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, value):
            sent.append(json.loads(value))

        def recv(self, **kwargs):
            task_id = sent[0]["header"]["task_id"]
            consumed.append(True)
            if len(consumed) == 1:
                return json.dumps({"header": {"task_id": task_id, "event": "task-started"}})
            if len(consumed) == 2:
                return b"\x01\x00"
            return json.dumps({"header": {"task_id": task_id, "event": "task-finished"}})

    monkeypatch.setattr("app.integrations.voice.tts.connect", lambda *a, **kw: Socket())
    stream = stream_question(
        Settings(
            bailian_api_key="fixture",
            bailian_base_url="https://fixture.cn-beijing.maas.aliyuncs.com",
        ),
        "问题？",
    )
    assert next(stream) == b"\x01\x00"
    assert len(consumed) == 2
    with pytest.raises(StopIteration):
        next(stream)
