"""Validate stored D01-D06 contents against the public, typed HTTP contract."""

from app.core import http_models as dto


def usage(*, tokens: int | None = None, search_count: int | None = None) -> dict:
    return {
        "tokens": tokens,
        "search_count": search_count,
        "call_seconds": None,
        "estimated_cost": None,
        "actual_cost": None,
        "currency": "CNY",
    }


def candidate_profile(facts: dict) -> dict:
    def value(key):
        fact = facts.get(key, {})
        return (
            str(fact["value"])
            if fact.get("status") == "stated" and fact.get("value") is not None
            else None
        )

    return {
        "display_name": value("name"),
        "current_role": value("current_role"),
        "experience_text": value("years_experience"),
        "education_text": value("education"),
    }


def validate_content(kind: str, value: dict) -> dict:
    content = dict(value)
    facts = content.get("facts", {})
    claims = [
        {
            "text": f"{key}: {fact['value']}" if fact.get("value") is not None else f"{key}: 未知",
            "evidence_refs": fact.get("evidence_refs", []),
            "category": "E2" if fact.get("status") == "stated" else "U",
        }
        for key, fact in facts.items()
    ]
    if kind == "D01":
        content.update(
            fields=[
                {
                    "name": key,
                    "value": str(fact["value"]) if fact.get("value") is not None else None,
                    "evidence_refs": fact.get("evidence_refs", []),
                }
                for key, fact in facts.items()
            ],
            conflicts=[key for key, fact in facts.items() if fact.get("status") == "conflict"],
        )
    elif kind == "D02":
        rules = content["rules"]
        content.update(
            dimensions=rules["interview_dimensions"],
            recommendation_policy=rules["recommendation_policy"],
            confirmation_status=content.get("confirmation_status", "draft"),
        )
    elif kind == "D03":
        content.update(
            profile=candidate_profile(facts),
            employment=[
                {
                    "text": "；".join(
                        str(fact["value"])
                        for fact in [item["name"], item.get("period"), *item["facts"].values()]
                        if fact and fact.get("status") == "stated"
                    ),
                    "evidence_refs": [
                        ref
                        for fact in [item["name"], item.get("period"), *item["facts"].values()]
                        if fact
                        for ref in fact.get("evidence_refs", [])
                    ],
                    "category": "E2",
                }
                for item in content.get("research_objects", [])
                if item["kind"] == "company"
            ],
            projects=[
                {
                    "text": str(item["name"]["value"] or "名称未知"),
                    "evidence_refs": item["name"].get("evidence_refs", []),
                    "category": "E2" if item["name"]["status"] == "stated" else "U",
                }
                for item in content.get("research_objects", [])
                if item["kind"] == "project"
            ],
            skills=[str(facts["skills"]["value"])]
            if facts.get("skills", {}).get("status") == "stated"
            else [],
            education=[
                claim for key, claim in zip(facts, claims, strict=True) if key == "education"
            ],
            claims=claims,
        )
    elif kind == "D04":
        content.setdefault("subjects", [])
        content.setdefault("findings", [])
        content.setdefault("usage", usage(search_count=0))
        if isinstance(content.get("stop_reason"), str):
            content["stop_reason"] = {
                "code": content["stop_reason"],
                "message": "未配置检索接口",
                "missing_fields": ["search_provider"],
            }
    elif kind == "D05":
        content.update(
            experience_context="简历陈述尚未独立核实",
            match_signals=claims,
            gaps=content.get("research_gaps", []),
            verification_questions=["请核实个人贡献及简历陈述"],
        )
    elif kind == "D06":
        mapping = {"met": "satisfied", "mismatch": "not_satisfied", "unknown": "unknown"}
        content.update(
            conditions=[
                {
                    "condition_id": check["condition_id"],
                    "result": mapping[check["status"]],
                    "reason": "按发布的结构化条件和当前证据核验",
                    "evidence_refs": check["evidence_refs"],
                }
                for check in content.get("checks", [])
            ],
            conclusion=content["result"],
            override_of_ref=content.get("review", {}).get("original_ref"),
        )
    model = getattr(dto, kind + "Content", None)
    if model is None:
        raise ValueError("Unsupported artifact content; B must register its typed writer")
    return model.model_validate(content).model_dump(mode="json")
