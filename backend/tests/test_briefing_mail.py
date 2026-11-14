import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.modules.outreach.briefing_mail import execute_briefing_mail, validate_email
from app.modules.outreach.models import ModelStep, OutreachCase
from app.modules.outreach.steps import register_step, retry_step


@pytest.mark.parametrize(
    "email",
    [
        "person@qq.com",
        "person@163.com",
        "person@gmail.com",
        "person@outlook.com",
        "person@company.cn",
    ],
)
def test_recipient_providers(email):
    assert validate_email(email) == email


def test_email_header_injection_rejected():
    with pytest.raises(ValueError):
        validate_email("a@example.com\r\nBcc: x@example.com")


def test_mail_unknown_outcome_is_never_retried(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'mail.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            OutreachCase(
                id="case",
                organization_id="org",
                owner_id="owner",
                application_id="app",
                candidate_id="candidate",
                job_id="job",
                snapshot={},
                session_data={},
            )
        )
        session.flush()
        task, _ = register_step(session, "case", "briefing_email_test", 1)
        task.detail = {"recipient": "person@example.com", "material": {}}
        task_id = task.id
    calls = []

    def smtp(*args, **kwargs):
        calls.append(True)
        raise TimeoutError()

    monkeypatch.setattr("app.modules.outreach.briefing_mail.smtplib.SMTP_SSL", smtp)
    settings = Settings(
        smtp_host="smtp.example.com",
        smtp_username="test",
        smtp_password="placeholder",
        smtp_sender="sender@example.com",
    )
    execute_briefing_mail(engine, settings, task_id)
    execute_briefing_mail(engine, settings, task_id)
    assert len(calls) == 1
    with Session(engine) as session:
        task = session.get(ModelStep, task_id)
        assert task.detail["delivery_status"] == "unknown"
        with pytest.raises(ValueError, match="RECONCILIATION"):
            retry_step(task, session.get(OutreachCase, "case"), "owner")
