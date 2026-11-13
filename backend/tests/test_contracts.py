import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.contracts import ScreeningPassedEvent


@pytest.fixture
def event_data() -> dict:
    fixture = (
        Path(__file__).resolve().parents[2] / "docs/contracts/day1_screening_passed.example.json"
    )
    return json.loads(fixture.read_text(encoding="utf-8"))


def test_handoff_fixture_keeps_mock_provenance_and_no_contact_permission(event_data):
    event = ScreeningPassedEvent.model_validate(event_data)
    assert event.fixture_only is True
    assert event.contact_authorization_ref is None
    assert event.source_modes.phone == "mock"
    assert event.rule_pack_ref.is_test_rule is True


@pytest.mark.parametrize("missing_artifact", ["D01", "D02", "D03", "D04", "D05", "D06"])
def test_handoff_rejects_incomplete_upstream_snapshot(event_data, missing_artifact):
    data = deepcopy(event_data)
    del data["artifact_refs"][missing_artifact]
    with pytest.raises(ValidationError):
        ScreeningPassedEvent.model_validate(data)


def test_handoff_rejects_unpublished_rules(event_data):
    event_data["rule_pack_ref"]["publication_status"] = "draft"
    with pytest.raises(ValidationError):
        ScreeningPassedEvent.model_validate(event_data)


def test_handoff_rejects_local_time_without_timezone(event_data):
    event_data["occurred_at"] = "2026-11-13T09:00:00"
    with pytest.raises(ValidationError):
        ScreeningPassedEvent.model_validate(event_data)
