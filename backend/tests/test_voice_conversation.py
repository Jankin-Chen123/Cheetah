import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.outreach.conversation import consent
from app.modules.outreach.invitations import issue_invitation
from app.modules.outreach.models import ModelStep, OutreachCase


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("有，我正在找工作。", True),
        ("可以继续。", True),
        ("有的，有的。", True),
        ("有的。", True),
        ("已经了解了，愿意继续", True),
        ("没有需求，谢谢", False),
        ("没有", False),
        ("没有。", False),
        ("没有啊", False),
        ("我不愿意继续", False),
        ("不是不愿意，不过想问下薪资", None),
        ("这个机会在哪里？", None),
        ("可能吧", None),
    ],
)
def test_spoken_consent_is_conservative(text, expected):
    assert consent(text) is expected


@pytest.mark.parametrize("decline", [False, True])
def test_voice_preflight_stream_answer_replay_and_stop(monkeypatch, decline):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.modules.outreach.router.database_session", lambda request: Session(engine)
    )
    with Session(engine) as db, db.begin():
        case = OutreachCase(
            id="voice-case",
            organization_id="org",
            owner_id="owner",
            application_id="app",
            candidate_id="candidate",
            job_id="job",
            revision=1,
            status="in_progress",
            stop_status="none",
            snapshot={"fixture_only": True},
            session_data={
                "preflight_required": True,
                "current_question": {"id": "q1", "question": "请介绍个人职责。"},
            },
        )
        invitation = issue_invitation(case)
        from app.modules.outreach.processing_permissions import record_processing_permission

        for purpose in ["formal_interview", "transcription", "extraction", "evaluation"]:
            record_processing_permission(db, case, purpose, True, case.revision)
        db.add(case)
    headers = {"Origin": "http://localhost:5173", "Authorization": "Bearer " + invitation["token"]}
    spoken = []

    def speech(settings, text, **kwargs):
        spoken.append(text)
        return {"pcm": b"\x00\x00", "sample_rate": 24000, "model": "fixture"}

    monkeypatch.setattr("app.integrations.voice.tts.synthesize_question", speech)
    utterance = ""

    async def transcribe(settings, frames, emit):
        async for _ in frames:
            pass
        await emit({"type": "transcript_delta", "text": utterance})
        return {"text": utterance, "model": "fixture-asr", "source_mode": "mock"}

    monkeypatch.setattr("app.integrations.voice.streaming.transcribe_stream", transcribe)
    with TestClient(create_app(Settings())) as client:
        path = "/api/v1/candidate/calls/voice-case"
        value = client.get(path, headers=headers).json()
        assert "是否有找工作" in value["spoken_prompt"]
        assert (
            client.post(
                path + "/speech", headers=headers, json={"expected_revision": value["revision"]}
            ).status_code
            == 200
        )
        assert "是否有找工作" in spoken[0]

        def turn(text):
            nonlocal utterance, value
            utterance = text
            revision = value["revision"]
            with client.websocket_connect(path + "/stream", headers=headers) as ws:
                ws.send_json({"token": invitation["token"], "expected_revision": revision})
                assert ws.receive_json()["type"] == "ready"
                ws.send_bytes(b"\x00\x00")
                ws.send_text("finish")
                assert ws.receive_json()["text"] == text
                result = ws.receive_json()
            body = {
                "action": "voice",
                "expected_revision": revision,
                "statement": text,
                "transcription_task_id": result["transcription_task_id"],
            }
            response = client.post(path, headers=headers, json=body)
            assert response.status_code == 200, response.text
            assert client.post(path, headers=headers, json=body).status_code == 409
            value = response.json()

        turn("我还不确定")
        assert value["preflight"]["interested"] is None
        assert value["decision_status"] == "pending"
        from app.modules.outreach.conversation_worker import execute_conversation

        monkeypatch.setattr(
            "app.modules.outreach.conversation_worker.generate_json",
            lambda *args: {"content": {"reply": "请问您愿意继续了解岗位吗？"}, "model": "fixture"},
        )
        with Session(engine) as db:
            task_id = db.scalar(select(ModelStep.id).where(ModelStep.step == "conversation"))
        execute_conversation(engine, Settings(), task_id)
        value = client.get(path, headers=headers).json()
        assert value["decision_status"] == "completed"
        assert value["preflight"]["interested"] is None
        if decline:
            turn("没有")
            assert value["status"] == "ended" and value["stop_status"] == "confirmed"
            assert (
                client.post(
                    path + "/speech", headers=headers, json={"expected_revision": value["revision"]}
                ).status_code
                == 409
            )
            goodbye = client.post(
                path + "/speech",
                headers=headers,
                json={"expected_revision": value["revision"] - 1, "farewell": True},
            )
            assert goodbye.status_code == 200
            assert "再见" in spoken[-1]
            return
        turn("有，我正在找工作")
        assert value["preflight"]["interested"] is True
        assert value["preflight"]["confirmed"] is False
        assert "薪资范围：暂未提供" in value["spoken_prompt"]
        assert value["question"] is None
        assert "随后再确认" in value["spoken_prompt"]
        turn("可以继续。")
        assert value["preflight"]["confirmed"] is False
        assert "薪资范围" in value["spoken_prompt"]
        value = client.post(
            path,
            headers=headers,
            json={
                "action": "briefing_presented",
                "expected_revision": value["revision"],
                "statement": "岗位已介绍且邮件状态已提示",
            },
        ).json()
        assert value["preflight"]["briefing_presented"] is True
        assert "愿意继续面试" in value["spoken_prompt"]
        turn("已经了解了，愿意继续")
        assert value["preflight"]["confirmed"] is True
        assert value["spoken_prompt"] == "请介绍个人职责。"
        turn("我负责设计缓存和排查线上故障")
        assert value["decision_status"] == "pending"
        with Session(engine) as db:
            current = db.get(OutreachCase, "voice-case")
            trace = current.session_data["answers"][0]["audio_transcription"]
            assert trace["source_mode"] == "mock"
            assert trace["submission_mode"] == "automatic_voice"
            assert trace["candidate_confirmed"] is False
            assert len(list(db.scalars(select(ModelStep).where(ModelStep.step == "followup")))) == 1
        stopped = client.post(
            path,
            headers=headers,
            json={
                "action": "stop",
                "expected_revision": value["revision"],
                "statement": "点击挂断",
            },
        )
        assert stopped.json()["stop_status"] == "confirmed"
