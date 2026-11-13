"""Versioned A/B handoff contract. No business execution is implemented here."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceMode(StrEnum):
    LIVE = "live"
    MOCK = "mock"
    MANUAL = "manual"


class ArtifactRef(ContractModel):
    artifact_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class EvidenceRef(ContractModel):
    evidence_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class RulePackRef(ContractModel):
    rule_pack_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    publication_status: Literal["published"]
    is_test_rule: bool


class ContactAuthorizationRef(ContractModel):
    authorization_id: str = Field(min_length=1)
    version: int = Field(ge=1)


class SourceModes(ContractModel):
    candidate_material: SourceMode
    model: SourceMode
    research: SourceMode
    phone: SourceMode


class ScreeningPassedEvent(ContractModel):
    protocol_version: Literal["1.0"]
    fixture_only: bool = False
    event_id: str = Field(min_length=1)
    event_type: Literal["screening.passed"]
    occurred_at: datetime
    organization_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    screening_result: Literal["passed"]
    rule_pack_ref: RulePackRef
    artifact_refs: dict[str, ArtifactRef]
    evidence_refs: list[EvidenceRef]
    contact_authorization_ref: ContactAuthorizationRef | None
    source_modes: SourceModes
    business_dedup_key: str = Field(min_length=1)
    expected_receiver_action: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def require_upstream_artifacts(cls, value: dict[str, ArtifactRef]) -> dict[str, ArtifactRef]:
        if set(value) != {f"D{number:02}" for number in range(1, 7)}:
            raise ValueError("The P0 handoff requires exactly D01 through D06")
        return value
