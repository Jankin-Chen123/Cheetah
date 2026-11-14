import asyncio
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.invitations import issue_invitation
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.router import candidate_audio_stream


def test_completed_stream_stop_is_programmatic_and_persisted(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        case = OutreachCase(
            id="stream-stop",
            organization_id="fixture",
            owner_id="fixture",
            application_id="fixture",
            candidate_id="fixture",
            job_id="fixture",
            revision=1,
            status="in_progress",
            stop_status="none",
            snapshot={},
            session_data={},
        )
        invitation = issue_invitation(case)
        revision = case.revision
        db.add(case)
    monkeypatch.setattr(
        "app.modules.outreach.router.database_session", lambda request: Session(engine)
    )

    async def transcribe(*args):
        return {"text": "请结束面试", "model": "fixture", "source_mode": "mock"}

    monkeypatch.setattr("app.integrations.voice.streaming.transcribe_stream", transcribe)
    sent = []

    class Socket:
        headers = {"origin": "http://localhost:5173"}
        app = SimpleNamespace(state=SimpleNamespace(settings=Settings()))

        async def accept(self):
            pass

        async def close(self, **kwargs):
            pass

        async def receive_json(self):
            return {"token": invitation["token"], "expected_revision": revision}

        async def send_json(self, data):
            sent.append(data)

    asyncio.run(candidate_audio_stream(Socket(), "stream-stop"))
    assert sent[-1]["stopped"] is True
    with Session(engine) as db:
        case = db.get(OutreachCase, "stream-stop")
        assert case.status == "ended" and case.stop_status == "confirmed"
        assert case.session_data["candidate_stop_statement"] == "请结束面试"
        assert db.get(ModelStep, sent[-1]["transcription_task_id"]).status == "completed"
