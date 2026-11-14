"""Persistent outreach state and immutable artifact versions."""

from sqlalchemy import JSON, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OutreachCase(Base):
    __tablename__ = "outreach_cases"
    __table_args__ = (UniqueConstraint("organization_id", "application_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(128))
    application_id: Mapped[str] = mapped_column(String(128))
    candidate_id: Mapped[str] = mapped_column(String(128))
    job_id: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="waiting_conditions")
    stop_status: Mapped[str] = mapped_column(String(24), default="none")
    snapshot: Mapped[dict] = mapped_column(JSON)
    session_data: Mapped[dict] = mapped_column(JSON, default=dict)


class ReceivedEvent(Base):
    __tablename__ = "outreach_received_events"
    __table_args__ = (UniqueConstraint("organization_id", "event_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128))
    event_id: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    case_id: Mapped[str] = mapped_column(String(64))


class OutreachArtifact(Base):
    __tablename__ = "outreach_artifacts"
    __table_args__ = (UniqueConstraint("case_id", "type", "version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(3))
    version: Mapped[int] = mapped_column(Integer)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(24), default="pending_review")
    content: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    input_refs: Mapped[list] = mapped_column(JSON)


class ReportAudit(Base):
    __tablename__ = "report_audits"
    __table_args__ = (UniqueConstraint("report_id", "action", "request_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(128))
    actor_id: Mapped[str] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSON)


class ModelStep(Base):
    __tablename__ = "model_steps"
    __table_args__ = (UniqueConstraint("case_id", "step", "input_revision"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    step: Mapped[str] = mapped_column(String(64))
    input_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict] = mapped_column(JSON)
