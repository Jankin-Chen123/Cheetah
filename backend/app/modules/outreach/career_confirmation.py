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


def field_target(resume, path, *, replay=False):
    def extend_slots(rows, index, factory):
        if isinstance(rows, list) and index < 100 and (replay or index == len(rows)):
            rows.extend(factory() for _ in range(index + 1 - len(rows)))

    parts = path.split(".")
    if any(part.isdigit() and (not part.isascii() or str(int(part)) != part) for part in parts):
        raise ValueError("CAREER_FIELD_INVALID")
    if (
        len(parts) == 4
        and parts[0] == "employment"
        and parts[1].isdigit()
        and parts[2] in {"responsibilities", "achievements"}
        and parts[3].isdigit()
    ):
        rows = resume.setdefault("employment", [])
        index, item_index = int(parts[1]), int(parts[3])
        extend_slots(rows, index, dict)
        if isinstance(rows, list) and index < len(rows) and isinstance(rows[index], dict):
            values = rows[index].setdefault(parts[2], [])
            extend_slots(values, item_index, str)
            if isinstance(values, list) and item_index < len(values) and item_index < 100:
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
        extend_slots(rows, index, str)
        if isinstance(rows, list) and index < len(rows) and index < 100:
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
        extend_slots(rows, index, dict)
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
    if (
        not answer
        or quote not in answer["text"]
        or value not in quote
        or not answer_matches_minutes(answer, minutes)
    ):
        raise ValueError("CAREER_SOURCE_QUOTE_INVALID")
    upstream, _ = confirmed_upstream(case, minutes)
    field_target(upstream.setdefault("D03", {}), field_path)
    conflicts = minutes.content.get("conflicts", [])
    if conflict_index is not None and (
        type(conflict_index) is not int or conflict_index < 0 or conflict_index >= len(conflicts)
    ):
        raise ValueError("CAREER_CONFLICT_REFERENCE_INVALID")
    linked = next(
        (
            link
            for link in minutes.content.get("career_conflict_evidence", [])
            if link["conflict_index"] == conflict_index
        ),
        None,
    )
    if linked and (
        linked["field_path"] != field_path
        or linked["answer_id"] != answer_id
        or linked["answer_quote"] != quote
        or linked["spoken_value"] != value.strip()
    ):
        raise ValueError("CAREER_CONFLICT_EVIDENCE_MISMATCH")
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


def answer_matches_minutes(answer, minutes):
    qa = minutes.content.get("qa")
    # Older artifacts may not contain an answer snapshot. Do not skip verification
    # for a current-format artifact with an empty or mismatching snapshot.
    return qa is None or any(
        item["id"] == answer["id"]
        and item.get("version", 1) == answer.get("version", 1)
        and item["text"] == answer["text"]
        for item in qa
    )


def unresolved_career_conflicts(case, minutes, confirmations):
    if minutes is None:
        return []
    resolved = set()
    for receipt in confirmations:
        index = receipt.get("conflict_index")
        if index is None:
            continue
        for link in minutes.content.get("career_conflict_evidence", []):
            if (
                link["conflict_index"] != index
                or link["field_path"] != receipt["field_path"]
                or link["answer_id"] != receipt["answer_id"]
                or link["answer_quote"] != receipt["quote"]
                or link["spoken_value"] != receipt["value"]
            ):
                continue
            if validate_career_conflict_link(case, link, minutes.content.get("qa", [])):
                resolved.add(index)
    return [
        conflict
        for index, conflict in enumerate(minutes.content.get("conflicts", []))
        if index not in resolved
    ]


def validate_career_conflict_link(case, link, answers):
    # Only a closed set of objective career fields can clear a report conflict.
    path = link["field_path"]
    if path not in {
        "profile.current_city",
        "profile.current_employer",
        "profile.current_role",
        "profile.current_employment_status",
        "job_preferences.target_role",
        "job_preferences.target_location",
        "job_preferences.salary_expectation",
        "job_preferences.availability",
    }:
        return False
    resume = case.session_data.get("upstream_content", {}).get("D03", {})
    section, field = path.split(".")
    source = resume.get(section, {}) if isinstance(resume, dict) else {}
    original, spoken = link["resume_value"], link["spoken_value"]
    return (
        isinstance(source, dict)
        and bool(original.strip() and spoken.strip())
        and source.get(field) == original
        and spoken.strip() != original.strip()
        and spoken in link["answer_quote"]
        and any(
            answer["id"] == link["answer_id"] and link["answer_quote"] in answer["text"]
            for answer in answers
        )
    )


def confirmed_upstream(case, minutes):
    upstream = deepcopy(case.session_data.get("upstream_content", {}))
    applied = []
    if minutes is None or not minutes.valid or minutes.case_id != case.id or minutes.type != "D08":
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
            or receipt["value"] not in receipt["quote"]
            or not answer_matches_minutes(answer, minutes)
        ):
            continue
        # Keep path indexes stable when an earlier, independently confirmed slot expires.
        # Stage writes so malformed historical receipts cannot pollute the projection.
        candidate = deepcopy(upstream.get("D03", {}))
        try:
            target, key = field_target(candidate, receipt["field_path"], replay=True)
        except (ValueError, AttributeError):
            continue
        target[key] = receipt["value"]
        upstream["D03"] = candidate
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
