"""Local integration response contracts, distinct from internal event contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class TaskAccepted(BaseModel):
    task_id: str
    resource_type: Literal["call"]
    resource_id: str
    poll_after_ms: int = Field(ge=100)
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = None


class ModelTaskView(BaseModel):
    id: str
    kind: Literal["D07", "followup", "D08", "D09", "D10"]
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    resource_type: Literal["call"]
    resource_id: str
    input_revision: int = Field(ge=1)
    detail: dict
    poll_after_ms: int = Field(ge=100)


class ReviewResult(BaseModel):
    id: str
    version: int = Field(ge=1)
    revision: int = Field(ge=1)
    status: Literal["approved", "rejected"]


class CallView(BaseModel):
    id: str
    application_id: str
    candidate_id: str
    job_id: str
    revision: int = Field(ge=1)
    status: str
    stop_status: str
    fixture_only: bool
    inherited_source_modes: list[str]
    session: dict
    upstream_refs: dict


class ArtifactView(BaseModel):
    id: str
    type: str
    version: int = Field(ge=1)
    valid: bool
    revision: int = Field(ge=1)
    review_status: str
    content: dict
    provenance: dict
    input_refs: list[dict]


class ActiveStepView(BaseModel):
    id: str
    status: str
    step: str


class FailedStepView(ActiveStepView):
    input_revision: int = Field(ge=1)
    error_code: str | None
    retry_count: int = Field(ge=0)


class CallDetailView(CallView):
    failed_tasks: list[FailedStepView]
    active_tasks: list[ActiveStepView]
    artifacts: list[ArtifactView]


class CallListView(BaseModel):
    items: list[CallView]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=0)
