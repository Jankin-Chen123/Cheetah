import pytest

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.budget import reserve_model_request
from app.modules.outreach.models import OutreachCase


def test_case_request_cap_counts_reserved_attempts():
    case = OutreachCase(session_data={})
    settings = Settings(model_max_requests_per_case=2)
    assert reserve_model_request(case, settings, "D07") == 1
    assert reserve_model_request(case, settings, "D07") == 2
    with pytest.raises(ModelUnavailable, match="BUDGET_EXCEEDED"):
        reserve_model_request(case, settings, "D07")
    assert case.session_data["model_requests_reserved"] == 2
