from types import SimpleNamespace

import pytest

from app.modules.outreach.client_sharing import require_client_sharing


@pytest.mark.parametrize("status", ["AUTHORIZED", "UNKNOWN", "WITHDRAWN", "RESTRICTED"])
def test_client_share_is_scoped_and_independent_of_interview_permission(status):
    scope = {"client_company_id": "fixture-client", "job_id": "fixture-job"}
    case = SimpleNamespace(
        snapshot={},
        session_data={
            "client_context": scope,
            "processing_permissions": {"evaluation": {"status": "AUTHORIZED"}},
            "client_sharing": {
                "status": status,
                "scope": dict(scope),
                "receipt_id": "fixture-receipt",
            },
        },
    )
    if status == "AUTHORIZED":
        require_client_sharing(case)
        case.session_data["client_context"] = {**scope, "client_company_id": "another-client"}
    with pytest.raises(ValueError, match="CLIENT_SHARING_PERMISSION_REQUIRED"):
        require_client_sharing(case)
