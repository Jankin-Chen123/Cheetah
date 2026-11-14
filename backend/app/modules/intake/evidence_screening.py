"""A05 evidence-based screening: models explain; the host validates and computes."""

import json
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.artifacts import artifact_ref, latest, save_artifact
from app.core.errors import DomainError
from app.core.models import Artifact, Evidence, RulePack, utcnow
from app.modules.intake.form_contracts import DIMENSIONS, PORTRAIT_FIELDS, ScreeningAssessment
from app.modules.intake.schemas import RuleContent


def uses_evidence_method(rule):
    return bool(
        rule and (rule.content.get("method_config_ref") or {}).get("config_id") == "a05-evidence"
    )


def screening_inputs(db, job, application):
    rule = db.get(RulePack, (job.id, application.rule_version))
    d03, d04 = (latest(db, job.id, kind, application.id) for kind in ("D03", "D04"))
    if not rule or not d03 or not d04:
        raise DomainError("PRECONDITION_NOT_MET", "缺少已发布规则或当前有效简历与研究资料")
    d01, d02 = (
        db.get(Artifact, (ref["artifact_id"], ref["version"]))
        for ref in (rule.d01_ref, rule.d02_ref)
    )
    if any(a is None or a.status != "valid" or a.job_id != job.id for a in (d01, d02)):
        raise DomainError("PRECONDITION_NOT_MET", "绑定的岗位标准已失效")
    return rule, d01, d02, d03, d04


def allowed_evidence(db, application, d03, d04):
    result = {}
    statuses = {}

    def collect_statuses(value):
        if isinstance(value, list):
            for item in value:
                collect_statuses(item)
        elif isinstance(value, dict):
            if "value" in value and value.get("status") in {"stated", "unknown", "conflict"}:
                for ref in value.get("evidence_refs", []):
                    statuses[(ref["evidence_id"], ref["version"])] = value["status"]
            for item in value.values():
                collect_statuses(item)

    collect_statuses(d03.content)
    for ref in [*d03.evidence_refs, *d04.evidence_refs]:
        item = db.get(Evidence, (ref["evidence_id"], ref["version"]))
        if (
            item
            and item.status == "valid"
            and item.application_id == application.id
            and item.organization_id == application.organization_id
        ):
            category = item.category or (
                "E2" if item.source_type in {"resume", "manual_revision"} else "U"
            )
            if statuses.get((item.evidence_id, item.version)) in {"unknown", "conflict"}:
                category = "U"
            result[(item.evidence_id, item.version)] = {
                "evidence_id": item.evidence_id,
                "version": item.version,
                "category": category,
                "quote": item.quote,
                "source_type": item.source_type,
                "location": item.location,
                "public_url": item.public_url,
                "source_date": item.source_date.isoformat() if item.source_date else None,
            }
    return result


def model_context(db, job, application):
    rule, d01, d02, d03, d04 = screening_inputs(db, job, application)
    evidence = allowed_evidence(db, application, d03, d04)
    return json.dumps(
        {
            "job_id": job.id,
            "candidate_id": application.candidate_id,
            "application_id": application.id,
            "rule_version": rule.version,
            "rubric": rule.content["screening_rubric"],
            "D01": compact_facts(d01.content.get("job_form") or d01.content),
            "D02": [
                {"id": d["id"], "label": d["label"], "rubric": d["rubric"]}
                for d in d02.content["dimensions"]
            ],
            "D03": compact_facts(d03.content.get("resume_form") or d03.content),
            "D04": compact_research(d04.content),
            "allowed_evidence": [
                source
                for source in evidence.values()
                if source["quote"]
                and not any(key in str(source["location"]) for key in ("联系电话", "电子邮箱"))
            ],
            "assessment_date": utcnow().date().isoformat(),
        },
        ensure_ascii=False,
    )


def compact_facts(value):
    """Keep values, missingness and refs; transmit each source quote in the evidence map once."""
    if isinstance(value, list):
        return [compact_facts(item) for item in value]
    if isinstance(value, dict):
        return {
            key: compact_facts(item)
            for key, item in value.items()
            if key not in {"quote", "联系电话", "电子邮箱"}
        }
    return value


def compact_research(content):
    report = content.get("report")
    if not report:
        return {key: content.get(key) for key in ("status", "findings", "conflicts", "gaps")}
    return {
        "objects": [
            {
                "object_id": obj["object_id"],
                "kind": obj["kind"],
                "identity": obj["identity"]["status"],
                "fields": [
                    {
                        "field": field["field"],
                        "status": field["status"],
                        "findings": [
                            {
                                "text": finding["text"],
                                "category": finding["category"],
                                "evidence_refs": finding["evidence_refs"],
                                "historical_applicability": finding["historical_applicability"],
                                "conflict_with_a04": finding["conflict_with_a04"],
                            }
                            for finding in field["public_information"]
                        ],
                    }
                    for field in obj["fields"]
                ],
                "gaps": obj["gaps"],
            }
            for obj in report["objects"]
        ],
        "conflicts": content.get("conflicts", []),
        "gaps": content.get("gaps", []),
    }


def validate_assessment(assessment, rubric, evidence):
    if set(assessment.portrait) != set(PORTRAIT_FIELDS):
        raise ValueError("A05 portrait must contain all eight template fields")
    scores = {item.dimension_id: item for item in assessment.scores}
    if len(scores) != 7 or set(scores) != set(DIMENSIONS):
        raise ValueError("A05 must assess each of the seven dimensions exactly once")
    reused = defaultdict(set)
    for dimension in rubric.dimensions:
        item = scores[dimension.id]
        if not dimension.enabled and item.score is not None:
            raise ValueError("Disabled dimensions cannot have a score")
        categories = []
        for use in item.evidence:
            source = evidence.get((use.evidence_id, use.version))
            if source is None or source["category"] != use.category:
                raise ValueError("Unknown, stale or relabelled A05 evidence")
            categories.append(use.category)
            reuse = (use.evidence_id, use.version)
            if use.purpose in reused[reuse]:
                raise ValueError("Evidence reused mechanically across dimensions")
            reused[reuse].add(use.purpose)
        if item.score is not None and not {"E1", "E2"}.intersection(categories):
            raise ValueError(
                "A score needs actual E1/E2 evidence, not only unknowns or model analysis"
            )
        if (
            item.score is not None
            and dimension.id
            in {
                "responsibilities",
                "skills",
                "education_experience",
                "recent_relevance",
                "projects_preferences",
            }
            and "E2" not in categories
        ):
            raise ValueError("Public context alone cannot prove candidate experience or ability")
    if not set(assessment.significant_mismatch_dimensions) <= set(scores):
        raise ValueError("Unknown mismatch dimensions")
    for key in assessment.significant_mismatch_dimensions:
        if scores[key].score is None or scores[key].score > 4:
            raise ValueError("Significant mismatch needs a supported low score")
    if assessment.essential_qualification_failure:
        ref = assessment.essential_qualification_failure
        source = evidence.get((ref.evidence_id, ref.version))
        if not source or ref.category != source["category"] or ref.category not in {"E1", "E2"}:
            raise ValueError("Necessary qualification failure requires actual evidence")
        if assessment.failed_qualification not in rubric.necessary_qualifications:
            raise ValueError("Qualification veto is not in published job requirements")
    for question in assessment.handoff:
        if (
            set(question) != {"dimension_id", "fact", "clue", "priority"}
            or question["dimension_id"] not in scores
            or question["priority"] not in {"high", "normal", "low"}
        ):
            raise ValueError("Invalid A06 factual handoff")
    return scores


def compute_scores(rubric, scores):
    contribution = Decimal(0)
    coverage = Decimal(0)
    rows = []
    for dimension in rubric.dimensions:
        item = scores[dimension.id]
        weight = Decimal(str(dimension.weight))
        points = Decimal(item.score) / 10 * weight if item.score is not None else None
        if points is not None:
            coverage += weight
            contribution += points
        rows.append(
            {
                **item.model_dump(mode="json"),
                "label": DIMENSIONS[dimension.id][0],
                "weight": dimension.weight,
                "requirement": dimension.requirement,
                "interview_dimension_ids": dimension.interview_dimension_ids,
                "status": "not_applicable"
                if not dimension.enabled
                else "not_evaluated"
                if item.score is None
                else "evaluated",
                "weighted_score": float(points) if points is not None else None,
            }
        )
    return {
        "weight_total": 100,
        "coverage": float(coverage),
        "contribution": float(contribution),
        "total": float(contribution) if coverage == 100 else None,
        "rows": rows,
    }


def finish_screening(db: Session, task, job, application, data):
    from app.modules.intake.service import audit, publish_handoff

    rule, d01, d02, d03, d04 = screening_inputs(db, job, application)
    rubric = RuleContent.model_validate(rule.content).screening_rubric
    if rubric is None:
        raise DomainError("RULES_INCOMPLETE", "缺少已发布的七维初筛标准")
    assessment = ScreeningAssessment.model_validate(data)
    assessment.unresolved_core_conflicts = list(
        dict.fromkeys([*assessment.unresolved_core_conflicts, *d04.content.get("conflicts", [])])
    )
    evidence = allowed_evidence(db, application, d03, d04)
    from app.modules.intake.salary import salary_score

    salary_dimension = next(d for d in rubric.dimensions if d.id == "salary")
    salary_item = next((s for s in assessment.scores if s.dimension_id == "salary"), None)
    if salary_item and salary_dimension.enabled:
        sources = [evidence.get((r.evidence_id, r.version), {}) for r in salary_item.evidence]
        expectations = [
            s.get("quote") or ""
            for s in sources
            if s.get("category") == "E2" and s.get("source_type") in {"resume", "manual_revision"}
        ]
        computed = {
            salary_score(q, expectation)
            for q in salary_dimension.source_quotes
            for expectation in expectations
        } - {None}
        salary_item.score = next(iter(computed)) if len(computed) == 1 else None
        if salary_item.score is None:
            salary_item.reason = (
                "双方薪资的币种、税前税后、固定/总包或周期口径未完整可比，保留未评估"
            )
    scores = validate_assessment(assessment, rubric, evidence)
    for dimension in rubric.dimensions:
        if (
            dimension.enabled
            and scores[dimension.id].score is None
            and not any(q["dimension_id"] == dimension.id for q in assessment.handoff)
        ):
            assessment.handoff.append(
                {
                    "dimension_id": dimension.id,
                    "fact": "补充核实" + DIMENSIONS[dimension.id][0] + "所需的事实",
                    "clue": scores[dimension.id].reason,
                    "priority": "high"
                    if dimension.id in {"responsibilities", "skills"}
                    else "normal",
                }
            )
    summary = compute_scores(rubric, scores)
    result = assessment.proposed_result
    safety_notes = []
    # A model may propose routing, but insufficient core evidence never qualifies automatically.
    core = [
        d
        for d in rubric.dimensions
        if d.enabled
        and d.id in {"responsibilities", "skills", "industry_context", "projects_preferences"}
    ]
    if result == "passed" and (
        not assessment.core_evidence_sufficient
        or assessment.unresolved_core_conflicts
        or any(scores[d.id].score is None for d in core)
        or any(scores[d.id].score is not None and scores[d.id].score <= 4 for d in core)
        or assessment.significant_mismatch_dimensions
        or assessment.essential_qualification_failure
    ):
        result = "manual_review"
        safety_notes.append("核心证据、主体冲突或必要资格待核对，未自动通过")
    if (
        result == "rejected"
        and len(set(assessment.significant_mismatch_dimensions) - {"salary"}) < 2
        and not assessment.essential_qualification_failure
    ):
        result = "manual_review"
        safety_notes.append("拒绝缺少多个核心不匹配或必要资格失败的充分依据")
    if assessment.unresolved_core_conflicts:
        result = "manual_review"
    refs = list(
        {
            (use.evidence_id, use.version): {"evidence_id": use.evidence_id, "version": use.version}
            for item in assessment.scores
            for use in item.evidence
        }.values()
    )
    if assessment.essential_qualification_failure:
        failure = assessment.essential_qualification_failure
        ref = {"evidence_id": failure.evidence_id, "version": failure.version}
        if ref not in refs:
            refs.append(ref)
    gaps = [
        DIMENSIONS[d.id][0] for d in rubric.dimensions if d.enabled and scores[d.id].score is None
    ]
    gaps += assessment.unresolved_core_conflicts + safety_notes
    mode = task.payload["execution_mode"]
    inputs = [artifact_ref(a) for a in (d01, d02, d03, d04)]
    portrait = save_artifact(
        db,
        job,
        "D05",
        {
            "facts": d03.content["facts"],
            "unknown_fields": d03.content["unknown_fields"],
            "portrait": assessment.portrait,
            "research_gaps": gaps,
            "verification_questions": [q["fact"] for q in assessment.handoff],
            "assessment_refs": {a.type: artifact_ref(a) for a in (d01, d02, d03, d04)},
            "form_context": {
                "客户企业": (d01.content.get("job_form") or {})
                .get("fields", {})
                .get("客户企业名称", {})
                .get("value"),
                "岗位名称": (d01.content.get("job_form") or {})
                .get("fields", {})
                .get("岗位名称", {})
                .get("value"),
                "用人部门": (d01.content.get("job_form") or {})
                .get("fields", {})
                .get("用人部门", {})
                .get("value"),
                "候选人编号": application.candidate_id,
                "候选人姓名": d03.content["facts"].get("name", {}).get("value"),
                "岗位评分规则版本": rule.version,
                "评估日期": utcnow().date().isoformat(),
            },
        },
        application=application,
        source=mode,
        inputs=inputs,
        evidence=refs,
        source_modes={"model": mode},
    )
    report = save_artifact(
        db,
        job,
        "D06",
        {
            "result": result,
            "checks": [],
            "gaps": gaps,
            "decision_method": rubric.method,
            "screening_rubric": rubric.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
            "score_summary": summary,
            "rule_version": rule.version,
            "safety_notes": safety_notes,
        },
        application=application,
        source=mode,
        inputs=[*inputs, artifact_ref(portrait)],
        evidence=refs,
        source_modes={"model": mode},
    )
    application.screening_result = result
    application.gaps = gaps
    application.stage = "outreach" if result == "passed" else "screening"
    application.revision += 1
    application.updated_at = utcnow()
    publish_handoff(db, job, application, rule, report)
    audit(
        db,
        job,
        "worker",
        "screening.completed",
        application_id=application.id,
        refs={"result": result, "d06_ref": artifact_ref(report), "method": rubric.method},
    )
    return [artifact_ref(portrait), artifact_ref(report)]
