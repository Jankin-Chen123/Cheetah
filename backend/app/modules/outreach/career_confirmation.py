"""Version-bound professional field confirmations; original evidence stays immutable."""

import time
from copy import deepcopy
from uuid import uuid4

from app.modules.outreach.artifacts import invalidate_downstream
from app.modules.outreach.models import OutreachArtifact

PROFILE_FIELDS = {
    "current_city",
    "current_employer",
    "current_role",
    "current_employment_status",
    "professional_direction",
}
PREFERENCE_FIELDS = {
    "target_role",
    "target_location",
    "salary_expectation",
    "availability",
    "other_conditions",
}
EMPLOYMENT_FIELDS = {
    "period",
    "company",
    "position",
    "department",
    "reports_to",
    "team_scope",
    "reason_for_leaving",
    "company_business",
}
EDUCATION_FIELDS = {"period", "institution", "major_or_course", "credential", "notes"}
PROJECT_FIELDS = {"name", "background", "role", "actions", "results"}
LIST_FIELDS = {
    "qualifications",
    "additional_projects_or_results",
    "career_preferences",
    "professional_skills",
}


def field_target(resume, path):
    parts = path.split(".")
    if (
        len(parts) == 4
        and parts[0] == "employment"
        and parts[1].isdigit()
        and parts[2] in {"responsibilities", "achievements"}
        and parts[3].isdigit()
    ):
        rows = resume.setdefault("employment", [])
        index, item_index = int(parts[1]), int(parts[3])
        if isinstance(rows, list) and index == len(rows) and index < 100:
            rows.append({})
        if isinstance(rows, list) and index < len(rows) and isinstance(rows[index], dict):
            values = rows[index].setdefault(parts[2], [])
            if isinstance(values, list) and item_index <= len(values) and item_index < 100:
                if item_index == len(values):
                    values.append("")
                return values, item_index
        raise ValueError("CAREER_FIELD_INVALID")
    if len(parts) == 2 and parts[0] == "job_preferences" and parts[1] in PREFERENCE_FIELDS:
        target = resume.setdefault("job_preferences", {})
        if isinstance(target, dict):
            return target, parts[1]
        raise ValueError("CAREER_SOURCE_STRUCTURE_INVALID")
    if len(parts) == 2 and parts[0] in LIST_FIELDS and parts[1].isdigit():
        rows = resume.setdefault(parts[0], [])
        index = int(parts[1])
        if isinstance(rows, list) and index <= len(rows) and index < 100:
            if index == len(rows):
                rows.append("")
            return rows, index
    if len(parts) == 2 and parts[0] == "profile" and parts[1] in PROFILE_FIELDS:
        target = resume.setdefault("profile", {})
        if isinstance(target, dict):
            return target, parts[1]
        raise ValueError("CAREER_SOURCE_STRUCTURE_INVALID")
    if (
        len(parts) == 3
        and parts[0] in {"employment", "education", "projects"}
        and parts[1].isdigit()
        and parts[2]
        in {
            "employment": EMPLOYMENT_FIELDS,
            "education": EDUCATION_FIELDS,
            "projects": PROJECT_FIELDS,
        }[parts[0]]
    ):
        rows = resume.setdefault(parts[0], [])
        index = int(parts[1])
        if isinstance(rows, list) and index == len(rows) and index < 100:
            rows.append({})
        if isinstance(rows, list) and index < len(rows) and isinstance(rows[index], dict):
            return rows[index], parts[2]
    raise ValueError("CAREER_FIELD_INVALID")


def confirm_field(
    session,
    case,
    *,
    expected_revision,
    minutes_id,
    minutes_version,
    field_path,
    value,
    answer_id,
    quote,
    reason,
    actor_id,
    conflict_index=None,
):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    minutes = session.get(OutreachArtifact, minutes_id)
    if (
        not minutes
        or minutes.case_id != case.id
        or minutes.type != "D08"
        or not minutes.valid
        or minutes.version != minutes_version
    ):
        raise ValueError("CURRENT_MINUTES_REQUIRED")
    if not all(isinstance(text, str) and text.strip() for text in (value, quote, reason)):
        raise ValueError("CAREER_CONFIRMATION_REQUIRED")
    answer = next((a for a in case.session_data.get("answers", []) if a["id"] == answer_id), None)
    if not answer or quote not in answer["text"] or value not in quote:
        raise ValueError("CAREER_SOURCE_QUOTE_INVALID")
    upstream = deepcopy(case.session_data.get("upstream_content", {}))
    field_target(upstream.setdefault("D03", {}), field_path)
    conflicts = minutes.content.get("conflicts", [])
    if conflict_index is not None and (
        type(conflict_index) is not int or conflict_index < 0 or conflict_index >= len(conflicts)
    ):
        raise ValueError("CAREER_CONFLICT_REFERENCE_INVALID")
    receipt = {
        "id": uuid4().hex,
        "minutes_ref": {"id": minutes.id, "version": minutes.version},
        "resume_ref": deepcopy(case.snapshot.get("artifact_refs", {}).get("D03")),
        "field_path": field_path,
        "value": value.strip(),
        "answer_id": answer_id,
        "answer_version": answer.get("version", 1),
        "quote": quote,
        "reason": reason.strip(),
        "actor_id": actor_id,
        "recorded_at": time.time(),
        "source_type": "MANUAL_CONFIRMATION",
        "conflict_index": conflict_index,
        "conflict_text": conflicts[conflict_index] if conflict_index is not None else None,
    }
    case.session_data = {
        **case.session_data,
        "career_confirmations": [*case.session_data.get("career_confirmations", []), receipt],
    }
    invalidate_downstream(session, case, "D09")
    case.revision += 1
    return receipt


def confirmed_upstream(case, minutes):
    upstream = deepcopy(case.session_data.get("upstream_content", {}))
    applied = []
    if minutes is None:
        return upstream, applied
    answers = {a["id"]: a for a in case.session_data.get("answers", [])}
    latest = {r["field_path"]: r for r in case.session_data.get("career_confirmations", [])}
    for receipt in latest.values():
        if any(
            r["confirmation_id"] == receipt.get("id")
            for r in case.session_data.get("career_confirmation_revocations", [])
        ):
            continue
        answer = answers.get(receipt["answer_id"])
        if (
            receipt["minutes_ref"] != {"id": minutes.id, "version": minutes.version}
            or receipt["resume_ref"] != case.snapshot.get("artifact_refs", {}).get("D03")
            or not answer
            or answer.get("version", 1) != receipt["answer_version"]
            or receipt["quote"] not in answer["text"]
        ):
            continue
        target, key = field_target(upstream.setdefault("D03", {}), receipt["field_path"])
        target[key] = receipt["value"]
        applied = [item for item in applied if item["field_path"] != receipt["field_path"]]
        applied.append(receipt)
    return upstream, applied


def revoke_confirmation(session, case, confirmation_id, expected_revision, reason, actor_id):
    if case.revision != expected_revision:
        raise ValueError("VERSION_CONFLICT")
    if not reason.strip():
        raise ValueError("CAREER_CONFIRMATION_REQUIRED")
    if not any(
        r.get("id") == confirmation_id for r in case.session_data.get("career_confirmations", [])
    ):
        raise ValueError("CAREER_CONFIRMATION_NOT_FOUND")
    revocations = case.session_data.get("career_confirmation_revocations", [])
    if any(r["confirmation_id"] == confirmation_id for r in revocations):
        raise ValueError("CAREER_CONFIRMATION_ALREADY_REVOKED")
    case.session_data = {
        **case.session_data,
        "career_confirmation_revocations": [
            *revocations,
            {
                "confirmation_id": confirmation_id,
                "reason": reason.strip(),
                "actor_id": actor_id,
                "recorded_at": time.time(),
            },
        ],
    }
    invalidate_downstream(session, case, "D09")
    case.revision += 1
