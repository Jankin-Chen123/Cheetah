import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.outreach.invitations import issue_invitation
from app.modules.outreach.models import ModelStep, OutreachArtifact, OutreachCase
from app.modules.outreach.preflight import briefing_snapshot, confirm_preflight


def test_candidate_answer_transaction_queue_and_stop(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.modules.outreach.router.database_session", lambda request: Session(engine)
    )
    with Session(engine) as db, db.begin():
        case = OutreachCase(
            id="candidate-case",
            organization_id="org",
            owner_id="owner",
            application_id="application",
            candidate_id="candidate",
            job_id="job",
            revision=1,
            status="in_progress",
            stop_status="none",
            snapshot={},
            session_data={
                "preflight_required": True,
                "preflight": {"interested": True, "confirmed": True},
                "current_question": {"id": "q1", "question": "职责？"},
            },
        )
        invitation = issue_invitation(case)
        import hashlib

        confirm_preflight(
            case,
            "已了解虚构材料且愿意开始",
            hashlib.sha256(
                json.dumps(briefing_snapshot(case), sort_keys=True).encode()
            ).hexdigest(),
        )
        db.add(case)
        db.add(
            OutreachArtifact(
                id="report",
                case_id=case.id,
                type="D10",
                version=1,
                valid=True,
                revision=1,
                review_status="approved",
                content={},
                provenance={},
                input_refs=[],
            )
        )
    headers = {"Origin": "http://localhost:5173", "Authorization": "Bearer " + invitation["token"]}
    with TestClient(create_app(Settings())) as client:
        path = "/api/v1/candidate/calls/candidate-case"
        with client.websocket_connect(
            path + "/stream", headers={"Origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"token": "invalid", "expected_revision": 1})
            assert socket.receive_json()["code"] == "STREAM_NOT_COMPLETED"
        assert client.get(path).status_code == 401
        view = client.get(path, headers=headers).json()
        speech_requests = []

        def speech(settings, text, **kwargs):
            speech_requests.append(text)
            return {"pcm": b"\x00\x00", "sample_rate": 24000, "model": "fixture"}

        monkeypatch.setattr("app.integrations.voice.tts.synthesize_question", speech)
        speech_body = {"expected_revision": view["revision"]}

        def speech_stream(*args, **kwargs):
            yield b"\x00\x00"

        monkeypatch.setattr("app.integrations.voice.tts.stream_question", speech_stream)
        streamed = client.post(path + "/speech-stream", headers=headers, json=speech_body)
        assert streamed.status_code == 200
        packets = [json.loads(line) for line in streamed.text.splitlines()]
        assert packets[0]["type"] == "audio"
        assert packets[-1]["type"] == "completed"

        spoken = client.post(path + "/speech", headers=headers, json=speech_body)
        assert spoken.status_code == 200
        assert (
            client.post(path + "/speech", headers=headers, json=speech_body).json() == spoken.json()
        )
        assert speech_requests == ["职责？"]
        requests = []

        def transcribe(*args, **kwargs):
            requests.append(True)
            return {"text": "虚构转写", "model": "fixture", "source_mode": "mock"}

        monkeypatch.setattr("app.integrations.voice.realtime.audio_roundtrip", transcribe)
        audio = {"expected_revision": view["revision"], "pcm_base64": "AAA="}
        first = client.post(path + "/transcription", headers=headers, json=audio)
        assert first.status_code == 200
        assert (
            client.post(path + "/transcription", headers=headers, json=audio).json() == first.json()
        )
        assert len(requests) == 1
        recovered = client.get(path, headers=headers).json()["transcription"]
        assert recovered["text"] == "虚构转写"
        assert recovered["task_id"] == first.json()["transcription_task_id"]
        assert (
            client.post(
                path + "/transcription", headers=headers, json={**audio, "pcm_base64": "AQE="}
            ).status_code
            == 409
        )
        body = {
            "expected_revision": view["revision"],
            "action": "answer",
            "statement": "虚构职责回答",
            "transcription_task_id": first.json()["transcription_task_id"],
        }
        result = client.post(path, headers=headers, json=body)
        assert result.status_code == 200
        assert client.post(path, headers=headers, json=body).status_code == 409
        with Session(engine) as db:
            tasks = list(db.scalars(select(ModelStep).where(ModelStep.step == "followup")))
            assert len(tasks) == 1 and tasks[0].step == "followup" and tasks[0].status == "queued"
            assert len(db.get(OutreachCase, "candidate-case").session_data["answers"]) == 1
            trace = db.get(OutreachCase, "candidate-case").session_data["answers"][0][
                "audio_transcription"
            ]
            assert trace["text"] == "虚构转写" and trace["edited"] is True
            assert trace["source_mode"] == "mock"
            assert db.get(OutreachArtifact, "report").valid is False
            assert db.get(OutreachArtifact, "report").review_status == "expired"
        stopped = client.post(
            path,
            headers=headers,
            json={
                "expected_revision": result.json()["revision"],
                "action": "stop",
                "statement": "结束面试",
            },
        )
        assert stopped.status_code == 200
        assert stopped.json()["stop_status"] == "confirmed"
        assert (
            client.post(
                path + "/speech",
                headers=headers,
                json={
                    "expected_revision": stopped.json()["revision"],
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                path,
                headers=headers,
                json={
                    "expected_revision": stopped.json()["revision"],
                    "action": "answer",
                    "statement": "迟到回答",
                },
            ).status_code
            == 409
        )
