"""Case-scoped request cap; caller must persist reservation before external execution."""

from app.core.config import Settings
from app.integrations.bailian import ModelUnavailable
from app.modules.outreach.models import OutreachCase


def reserve_model_request(case: OutreachCase, settings: Settings, step: str):
    used = case.session_data.get("model_requests_reserved", 0)
    limit = min(max(settings.model_max_requests_per_case, 1), 100)
    if used >= limit:
        raise ModelUnavailable("MODEL_REQUEST_BUDGET_EXCEEDED")
    case.session_data = {
        **case.session_data,
        "model_requests_reserved": used + 1,
        "model_request_limit": limit,
        "last_model_step": step,
    }
    return used + 1
