from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.artifacts import (
    artifact_ref,
    evidence_ref,
    get_artifact,
    get_evidence,
    latest,
    require_application_file,
    save_artifact,
)
from app.core.config import Settings
from app.core.contracts import ScreeningPassedEventV11
from app.core.errors import DomainError
from app.core.models import (
    Application,
    Artifact,
    AuditEntry,
    BatchItem,
    Evidence,
    Identity,
    IntakeJob,
    OutboxEvent,
    ResumeBatch,
    RulePack,
    StoredFile,
    Task,
    new_id,
    utcnow,
)
from app.core.tasks import enqueue
from app.modules.intake.schemas import RuleContent

CONFIGS = {
    "research_config_ref": {"unavailable", "bounded-research", "pi-research"},
    "phone_config_ref": {"disabled"},
    "method_config_ref": {"predicates", "a05-evidence"},
}


def require_revision(actual: int, expected: int):
    if actual != expected:
        raise DomainError(
            "VERSION_CONFLICT",
            "内容已更新，请重新读取",
            details={
                "current_revision": actual,
            },
        )


def check_mode(settings: Settings, mode: str):
    if mode == "mock" and not settings.allow_mock:
        raise DomainError("PERMISSION_DENIED", "模拟执行未开启", 403)


def rule_issues(content: RuleContent) -> list[dict]:
    fields = []
    for field in ("screening_text", "interview_text", "recommendation_text"):
        if not getattr(content, field):
            fields.append(field)
    evidence_method = bool(
        content.method_config_ref and content.method_config_ref.config_id == "a05-evidence"
    )
    if evidence_method and content.screening_rubric is None:
        fields.append("screening_rubric")
    if not evidence_method and not content.screening_conditions:
        fields.append("screening_conditions")
    if not content.interview_dimensions:
        fields.append("interview_dimensions")
    for group in (content.screening_conditions, content.interview_dimensions):
        if len({item.id for item in group}) != len(group):
            fields.append("duplicate_condition_or_dimension_id")
    for condition in content.screening_conditions:
        if (
            condition.predicate is None
            or not condition.required_evidence
            or not condition.evidence_sources
        ):
            fields.append("screening_conditions." + condition.id)
    for dimension in content.interview_dimensions:
        if not dimension.required_evidence:
            fields.append("interview_dimensions." + dimension.id)
        if evidence_method and (
            not dimension.anchors or not dimension.source_quotes or dimension.weight is None
        ):
            fields.append("interview_dimensions." + dimension.id)
    if (
        evidence_method
        and abs(sum(d.weight or 0 for d in content.interview_dimensions) - 1) > 0.00001
    ):
        fields.append("interview_dimensions.weights")
    if evidence_method and content.screening_rubric:
        ids = {d.id for d in content.interview_dimensions}
        if any(
            not set(d.interview_dimension_ids) <= ids for d in content.screening_rubric.dimensions
        ):
            fields.append("screening_rubric.interview_dimension_ids")
    dimensions = {item.id for item in content.interview_dimensions}
    policy = content.recommendation_policy
    if (
        policy is None
        or not policy.required_dimension_ids
        or not set(policy.required_dimension_ids) <= dimensions
    ):
        fields.append("recommendation_policy")
    elif policy.decision_method == "weighted_score":
        weights = [item.weight for item in content.interview_dimensions]
        if (
            policy.threshold is None
            or any(item is None for item in weights)
            or abs(sum(item or 0 for item in weights) - 1) > 0.0001
        ):
            fields.append("recommendation_policy.weights_or_threshold")
    for field, config_id in CONFIGS.items():
        ref = getattr(content, field)
        if ref is None or ref.config_id not in config_id or ref.version != 1:
            fields.append(field)
    return [
        {
            "path": [field],
            "code": "REQUIRED_OR_UNSUPPORTED",
            "message": "缺少已确认标准或使用了尚未支持的配置",
        }
        for field in sorted(set(fields))
    ]


def rule_ref(rule: RulePack) -> dict:
    return {
        "rule_pack_id": rule.rule_pack_id,
        "version": rule.version,
        "publication_status": "published",
        "is_test_rule": rule.is_test_rule,
    }


def audit(
    db: Session,
    job: IntakeJob,
    actor_id: str,
    action: str,
    *,
    application_id: str | None = None,
    refs: dict | None = None,
) -> AuditEntry:
    entry = AuditEntry(
        organization_id=job.organization_id,
        job_id=job.id,
        application_id=application_id,
        actor_id=actor_id,
        action=action,
        refs=refs or {},
    )
    db.add(entry)
    db.flush()
    return entry


def validate_job_inputs(db: Session, user: Identity, job: IntakeJob, refs: dict):
    for kind, ref in refs.items():
        artifact = get_artifact(db, user, ref, valid=True)
        if artifact.job_id != job.id or artifact.application_id or artifact.type != kind:
            raise DomainError("RULES_INCOMPLETE", "岗位产物引用不匹配")


def save_profile(
    db: Session,
    job: IntakeJob,
    profile: dict,
    kind: str,
    *,
    source: str,
    application: Application | None = None,
    inputs: list | None = None,
    inherited: list[str] | None = None,
) -> Artifact:
    refs = []
    if application and profile.get("resume_form"):
        file = db.get(StoredFile, application.file_id)
        profile["document_metadata"] = {
            "candidate_id": application.candidate_id,
            "filename": file.name,
            "format": "text"
            if file.media_type == "text/plain"
            else "PDF"
            if file.name.lower().endswith(".pdf")
            else "Word",
            "file_id": file.id,
        }
    statements = list(profile["facts"].items())
    if profile.get("job_form"):
        form = profile["job_form"]
        statements.extend(("job_form/" + key, value) for key, value in form["fields"].items())
        for section, values in form["jd"].items():
            statements.extend(
                (f"job_form/jd/{section}/{i}", value) for i, value in enumerate(values)
            )
    if profile.get("resume_form"):
        for section, records in profile["resume_form"]["sections"].items():
            for record in records:
                statements.extend(
                    (f"resume_form/{section}/{record['record_id']}/{key}", value)
                    for key, value in record["fields"].items()
                )
    for item in profile.get("research_objects", []):
        prefix = f"research_objects/{item['object_id']}"
        statements.append((prefix + "/name", item["name"]))
        if item.get("period"):
            statements.append((prefix + "/period", item["period"]))
        statements.extend((prefix + "/facts/" + key, value) for key, value in item["facts"].items())
    for key, fact in statements:
        quote = fact.get("quote")
        from app.modules.intake.analysis import job_material

        material = application.material_text if application else job_material(job)
        start = material.find(quote) if quote else -1
        evidence = Evidence(
            organization_id=job.organization_id,
            job_id=job.id,
            application_id=application.id if application else None,
            source_type="resume" if application else "job_material",
            category="U" if fact.get("status") != "stated" else "E2" if application else None,
            quote=quote,
            source_mode="mock" if source == "mock" else "manual",
            location={
                "field": key,
                "start": start if start >= 0 else None,
                "end": start + len(quote) if start >= 0 else None,
                "file_id": application.file_id if application else None,
            },
        )
        db.add(evidence)
        db.flush()
        ref = evidence_ref(evidence)
        fact["evidence_refs"] = [ref]
        if not key.startswith(("resume_form/", "job_form/")):
            fact["source_type"] = "resume" if application else "job_material"
        refs.append(ref)
    return save_artifact(
        db,
        job,
        kind,
        profile,
        application=application,
        source=source,
        inherited=inherited,
        inputs=inputs,
        evidence=refs,
    )


def queue_step(
    db: Session,
    job: IntakeJob,
    application: Application,
    kind: str,
    *,
    input_refs: list | None = None,
) -> Task:
    from app.modules.intake.agent_prompts import resource_fingerprint

    if input_refs is None and kind == "resume_parse":
        input_refs = [{"kind": "material", "id": application.file_id, "version": 1}]
    return enqueue(
        db,
        organization_id=job.organization_id,
        job_id=job.id,
        application_id=application.id,
        kind=kind,
        dedup_key=f"{application.id}:{application.generation}:{kind}",
        payload={
            "agent_spec_version": 2,
            "agent_resource_hash": resource_fingerprint(),
            "generation": application.generation,
            "rule_version": application.rule_version,
            "execution_mode": application.execution_mode,
            "input_refs": input_refs or [],
        },
    )


def screening_decision(profile: dict, content: RuleContent) -> tuple[str, list, list]:
    checks, gaps = [], []
    for condition in content.screening_conditions:
        pred = condition.predicate
        fact = profile["facts"].get(pred.field, {}) if pred else {}
        status = "unknown"
        available_sources = {fact.get("source_type", "resume")}
        if "manual_revision" in available_sources:
            available_sources.add("resume")
        if (
            pred
            and fact.get("status") == "stated"
            and fact.get("value") is not None
            and fact.get("evidence_refs")
            and set(condition.evidence_sources) <= available_sources
        ):
            value = fact["value"]
            if pred.operator == "gte":
                if isinstance(value, (int, float)) and isinstance(pred.expected, (int, float)):
                    status = "met" if value >= pred.expected else "mismatch"
            elif pred.operator == "contains":
                negated = any(
                    word in str(value).casefold()
                    for word in ("不会", "没有", "未使用", "不了解", "不熟悉", "not ", "no ")
                )
                status = (
                    "met"
                    if not negated and str(pred.expected).casefold() in str(value).casefold()
                    else "unknown"
                )
            else:
                status = (
                    "met" if str(value).casefold() == str(pred.expected).casefold() else "mismatch"
                )
        if status == "unknown":
            gaps.append(condition.id)
        checks.append(
            {
                "condition_id": condition.id,
                "status": status,
                "mismatch_action": condition.mismatch_action,
                "evidence_refs": fact.get("evidence_refs", []),
            }
        )
    if any(c["status"] == "mismatch" and c["mismatch_action"] == "reject" for c in checks):
        result = "rejected"
    elif gaps or not checks:
        result = "unknown"
    elif any(c["status"] == "mismatch" for c in checks):
        result = "manual_review"
    else:
        result = "passed"
    return result, checks, gaps


def publish_handoff(
    db: Session, job: IntakeJob, application: Application, rule: RulePack, d06: Artifact
) -> OutboxEvent | None:
    if application.screening_result != "passed" or application.status != "active":
        return None
    refs = {"D01": rule.d01_ref, "D02": rule.d02_ref}
    artifacts = [db.get(Artifact, (ref["artifact_id"], ref["version"])) for ref in refs.values()]
    for kind in ("D03", "D04", "D05", "D06"):
        artifact = latest(db, job.id, kind, application.id)
        if artifact is None:
            raise DomainError("PRECONDITION_NOT_MET", "缺少有效上游产物")
        artifacts.append(artifact)
        refs[kind] = artifact_ref(artifact)
    if any(artifact is None or artifact.status != "valid" for artifact in artifacts):
        raise DomainError("PRECONDITION_NOT_MET", "上游产物已失效")
    modes = {
        mode
        for artifact in artifacts
        for mode in [artifact.source_mode, *artifact.inherited_source_modes]
    }
    fixture = rule.is_test_rule or "mock" in modes
    dedup_key = f"screening:{application.id}:{d06.version}"
    existing = db.scalar(select(OutboxEvent).where(OutboxEvent.dedup_key == dedup_key))
    if existing:
        return existing
    event_id = new_id()
    payload = ScreeningPassedEventV11(
        protocol_version="1.1",
        fixture_only=fixture,
        event_id=event_id,
        event_type="screening.passed",
        occurred_at=utcnow(),
        organization_id=job.organization_id,
        job_id=job.id,
        candidate_id=application.candidate_id,
        application_id=application.id,
        workflow_id=application.workflow_id,
        screening_result="passed",
        rule_pack_ref=rule_ref(rule),
        artifact_refs=refs,
        evidence_refs=d06.evidence_refs,
        contact_authorization_ref=None,
        source_modes={
            "candidate_material": d06.source_modes.get("candidate_material") or "manual",
            "model": d06.source_modes.get("model") or "manual",
            "research": d06.source_modes.get("research"),
            "phone": None,
        },
        phone_execution_mode="mock" if fixture else "live",
        business_dedup_key=f"application:{application.id}",
        expected_receiver_action="create_or_reuse_call_task_and_recheck_current_prerequisites",
        notes=["研究的来源、主体核实程度和缺口见 D04。电话尚未执行；此事件不构成联系授权。"],
    )
    event = OutboxEvent(
        id=event_id,
        organization_id=job.organization_id,
        application_id=application.id,
        event_type="screening.passed",
        dedup_key=dedup_key,
        payload=payload.model_dump(mode="json"),
    )
    db.add(event)
    db.flush()
    return event


def validate_handoff(db: Session, event: OutboxEvent) -> ScreeningPassedEventV11:
    """B calls inside its consumption transaction, then uses business_dedup_key separately."""
    payload = ScreeningPassedEventV11.model_validate(event.payload)
    job = db.scalar(select(IntakeJob).where(IntakeJob.id == payload.job_id).with_for_update())
    application = db.get(Application, payload.application_id)
    owner = db.get(Identity, job.owner_id) if job else None
    if (
        job is None
        or owner is None
        or not owner.enabled
        or owner.organization_id != payload.organization_id
        or application is None
        or job.status != "active"
        or job.organization_id != payload.organization_id
        or application.status != "active"
        or application.screening_result != "passed"
        or application.job_id != job.id
        or application.organization_id != payload.organization_id
        or event.status != "pending"
        or event.id != payload.event_id
        or event.organization_id != payload.organization_id
        or event.application_id != payload.application_id
        or application.candidate_id != payload.candidate_id
        or application.workflow_id != payload.workflow_id
        or payload.business_dedup_key != f"application:{application.id}"
    ):
        raise DomainError("PRECONDITION_NOT_MET", "交接已失效或已消费")
    try:
        require_application_file(db, application)
    except DomainError:
        raise DomainError("PRECONDITION_NOT_MET", "交接原始材料已不可访问") from None
    rule = db.get(RulePack, (job.id, application.rule_version))
    if rule is None or rule_ref(rule) != payload.rule_pack_ref.model_dump():
        raise DomainError("PRECONDITION_NOT_MET", "规则引用失效")
    if (
        payload.artifact_refs["D01"].model_dump() != rule.d01_ref
        or payload.artifact_refs["D02"].model_dump() != rule.d02_ref
    ):
        raise DomainError("PRECONDITION_NOT_MET", "岗位产物与绑定规则快照不一致")
    for kind, ref in payload.artifact_refs.items():
        artifact = db.get(Artifact, (ref.artifact_id, ref.version))
        if (
            artifact is None
            or artifact.status != "valid"
            or artifact.type != kind
            or artifact.job_id != job.id
            or artifact.organization_id != payload.organization_id
            or artifact.application_id != (None if kind in {"D01", "D02"} else application.id)
        ):
            raise DomainError("PRECONDITION_NOT_MET", "产物引用失效")
    current = latest(db, job.id, "D06", application.id)
    if current is None or artifact_ref(current) != payload.artifact_refs["D06"].model_dump():
        raise DomainError("PRECONDITION_NOT_MET", "初筛已产生新版本")
    for ref in payload.evidence_refs:
        evidence = db.get(Evidence, (ref.evidence_id, ref.version))
        if (
            evidence is None
            or evidence.status != "valid"
            or evidence.job_id != job.id
            or evidence.application_id != application.id
            or evidence.organization_id != payload.organization_id
        ):
            raise DomainError("PRECONDITION_NOT_MET", "证据引用失效")
    return payload


def invalidate(
    db: Session,
    job: IntakeJob,
    application: Application,
    actor_id: str,
    reason: str,
    *,
    include_profile: bool = False,
) -> list[dict]:
    kinds = [f"D{number:02}" for number in range(3 if include_profile else 4, 11)]
    affected = list(
        db.scalars(
            select(Artifact).where(
                Artifact.application_id == application.id,
                Artifact.type.in_(kinds),
                Artifact.status == "valid",
            )
        )
    )
    for artifact in affected:
        artifact.status = "expired"
    db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.application_id == application.id,
            OutboxEvent.event_type == "screening.passed",
            OutboxEvent.status == "pending",
        )
        .values(status="invalidated")
    )
    # External requests are never considered cancelled merely by cancelling a local task.
    db.execute(
        update(Task)
        .where(
            Task.application_id == application.id,
            Task.status.in_(["queued", "running"]),
            Task.external_state.is_(None),
        )
        .values(status="cancelled", revision=Task.revision + 1, lease_token=None)
    )
    application.generation += 1
    application.revision += 1
    application.screening_result = "pending"
    application.stage = "intake"
    application.updated_at = utcnow()
    parent_ids = (
        select(ResumeBatch.task_id)
        .join(BatchItem, BatchItem.batch_id == ResumeBatch.id)
        .where(BatchItem.application_id == application.id)
    )
    db.execute(
        update(Task)
        .where(Task.id.in_(parent_ids))
        .values(
            status="waiting_conditions",
            error_code="RECOMPUTE_REQUIRED",
            revision=Task.revision + 1,
            finished_at=None,
        )
    )
    entry = audit(
        db,
        job,
        actor_id,
        "intake.invalidated",
        application_id=application.id,
        refs={"artifacts": [artifact_ref(item) for item in affected], "reason": reason},
    )
    db.add(
        OutboxEvent(
            organization_id=job.organization_id,
            application_id=application.id,
            event_type="intake.invalidated",
            dedup_key=f"invalidation:{entry.id}",
            payload={
                "event_id": entry.id,
                "protocol_version": "1.0",
                "application_id": application.id,
                "invalidated_refs": [artifact_ref(item) for item in affected],
                "required_action": "block_pending_contact_and_delivery_recheck_active_call",
            },
        )
    )
    db.flush()
    return [artifact_ref(item) for item in affected]


def validate_review_evidence(db: Session, user: Identity, application: Application, refs: list):
    for ref in refs:
        evidence = get_evidence(db, user, ref)
        if evidence.application_id != application.id or evidence.status != "valid":
            raise DomainError("PRECONDITION_NOT_MET", "证据不属于当前有效候选人材料")
