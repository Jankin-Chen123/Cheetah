import json
import re

from fastapi import APIRouter, Request
from sqlalchemy import select, update

from app.core import http_models as dto
from app.core.artifacts import (
    artifact_ref,
    get_application,
    get_artifact,
    get_job,
    latest,
    save_artifact,
)
from app.core.auth import Db, User
from app.core.errors import DomainError
from app.core.idempotency import execute
from app.core.models import (
    Artifact,
    AuditEntry,
    Evidence,
    OutboxEvent,
    RulePack,
    StoredFile,
    Task,
    aware,
    utcnow,
)
from app.core.tasks import accepted
from app.modules.intake.schemas import CorrectionInput, RecomputeInput, ScreeningReviewInput
from app.modules.intake.service import (
    audit,
    invalidate,
    publish_handoff,
    queue_step,
    require_revision,
    rule_ref,
    validate_review_evidence,
)

router = APIRouter(tags=["intake-corrections"])


@router.post(
    "/applications/{application_id}/corrections",
    status_code=201,
    response_model=dto.CorrectionResult,
)
def correct_profile(
    application_id: str, body: CorrectionInput, request: Request, db: Db, user: User
):
    def action():
        application = get_application(db, user, application_id, lock=True)
        job = get_job(db, user, application.job_id)
        target = get_artifact(db, user, body.target_artifact_ref.model_dump())
        if (
            application.status != "active"
            or target.application_id != application.id
            or target.type != "D03"
        ):
            raise DomainError("PRECONDITION_NOT_MET", "当前只支持更正有效 D03 结构化事实")
        current = latest(db, job.id, "D03", application.id)
        if current is None or artifact_ref(current) != body.target_artifact_ref.model_dump():
            raise DomainError("VERSION_CONFLICT", "请更正当前 D03 版本")
        rule = db.get(RulePack, (job.id, application.rule_version))
        allowed = {
            "name",
            "current_role",
            "skills",
            "education",
            "years_experience",
            "employer",
            "project",
            "location",
            "salary",
        } | set(target.content["facts"])
        allowed |= {c["predicate"]["field"] for c in rule.content["screening_conditions"]}
        objects = json.loads(json.dumps(target.content.get("research_objects", [])))
        form = json.loads(json.dumps(target.content.get("resume_form")))
        object_targets = {}
        for item in objects:
            prefix = f"/research_objects/{item['object_id']}"
            for field in ("name", "period"):
                object_targets[prefix + "/" + field] = (item, field)
            for field in item["facts"]:
                object_targets[prefix + "/facts/" + field] = (item["facts"], field)
        if form:
            for section, records in form["sections"].items():
                for record in records:
                    for field in record["fields"]:
                        path = f"/resume_form/{section}/{record['record_id']}/{field}"
                        object_targets[path] = (record["fields"], field)
        facts_to_change = {}
        for change in body.changes:
            match = re.fullmatch(r"/facts/([a-z][a-z0-9_]{0,63})", change.path)
            key = match[1] if match and match[1] in allowed else change.path
            if (
                not (match and match[1] in allowed) and key not in object_targets
            ) or key in facts_to_change:
                raise DomainError(
                    "VALIDATION_ERROR", "仅允许更正白名单事实路径，且同字段不可重复", 422
                )
            facts_to_change[key] = change.value
        validate_review_evidence(
            db, user, application, [ref.model_dump() for ref in body.evidence_refs]
        )
        blocked_ids = list(
            db.scalars(
                select(Task.id).where(
                    Task.application_id == application.id, Task.status.in_(["queued", "running"])
                )
            )
        )
        invalidated = invalidate(db, job, application, user.id, body.reason, include_profile=True)
        facts = json.loads(json.dumps(target.content["facts"]))
        for key, fact in facts_to_change.items():
            container, field = object_targets[key] if key in object_targets else (facts, key)
            previous_refs = (container.get(field) or {}).get("evidence_refs", [])
            previous = (
                db.get(Evidence, (previous_refs[0]["evidence_id"], previous_refs[0]["version"]))
                if previous_refs
                else None
            )
            if previous:
                previous.status = "expired"
            evidence = Evidence(
                evidence_id=previous.evidence_id if previous else None,
                version=previous.version + 1 if previous else 1,
                organization_id=user.organization_id,
                job_id=job.id,
                application_id=application.id,
                source_type="manual_revision",
                category="E2" if fact.status == "stated" else "U",
                corrects_ref=previous_refs[0] if previous_refs else None,
                quote=fact.quote,
                location={"field": key},
                source_mode="manual",
            )
            db.add(evidence)
            db.flush()
            ref = {"evidence_id": evidence.evidence_id, "version": evidence.version}
            container[field] = {
                **fact.model_dump(mode="json"),
                "evidence_refs": [ref],
                "source_type": "manual_revision",
            }
            if key.startswith("/resume_form/"):
                container[field].pop("source_type")
                container[field]["note"] = "人工更正：" + body.reason
            elif form:
                # Keep the complete form consistent with legacy summary/object corrections.
                aliases = {
                    "name": ("基本信息", "候选人姓名"),
                    "current_role": ("基本信息", "当前岗位"),
                    "employer": ("基本信息", "当前任职公司"),
                    "location": ("基本信息", "所在城市"),
                    "skills": ("专业技能", "专业技能"),
                }
                if key in aliases:
                    section, label = aliases[key]
                    form["sections"][section][0]["fields"][label] = {
                        **fact.model_dump(mode="json"),
                        "evidence_refs": [ref],
                    }
                elif key.startswith("/research_objects/"):
                    object_id = key.split("/")[2]
                    prior = target.content.get("research_objects") or []
                    original = next(item for item in prior if item["object_id"] == object_id)
                    old_fact = (
                        original.get(key.rsplit("/", 1)[-1])
                        if "/facts/" not in key
                        else original["facts"].get(key.rsplit("/", 1)[-1])
                    )
                    for records in form["sections"].values():
                        for record in records:
                            if record["record_id"] == object_id and old_fact:
                                for label, stored in record["fields"].items():
                                    if stored.get("value") == old_fact.get("value") and stored.get(
                                        "quote"
                                    ) == old_fact.get("quote"):
                                        record["fields"][label] = {
                                            **fact.model_dump(mode="json"),
                                            "evidence_refs": [ref],
                                        }
        if form:
            from app.modules.intake.form_contracts import ResumeForm
            from app.modules.intake.form_sources import canonical_resume_facts, resume_objects

            parsed_form = ResumeForm.model_validate(form)
            derived = canonical_resume_facts(parsed_form, persisted=True)
            changed_fields = {
                path.rsplit("/", 1)[-1]
                for path in facts_to_change
                if path.startswith("/resume_form/")
            }
            canonical_labels = {
                "name": "候选人姓名",
                "current_role": "当前岗位",
                "employer": "当前任职公司",
                "location": "所在城市",
                "skills": "专业技能",
            }
            for key, value in derived.items():
                if key in facts and (
                    value["status"] == "stated"
                    or key in facts_to_change
                    or canonical_labels[key] in changed_fields
                ):
                    # Source references are retained on the corresponding form value.
                    original = facts[key]
                    original.update(value)
            generated = {item["object_id"]: item for item in resume_objects(parsed_form)}
            previous_objects = {item["object_id"]: item for item in objects}
            for object_id, item in generated.items():
                previous = previous_objects.get(object_id, {})
                item["facts"] = {**previous.get("facts", {}), **item["facts"]}
            # Older versions and authorized supplemental clues may have no form record.
            # A field correction never silently deletes those independent objects.
            objects = list((previous_objects | generated).values())
        refs = [ref for fact in facts.values() for ref in fact.get("evidence_refs", [])]
        for item in objects:
            for fact in [item["name"], item.get("period"), *item["facts"].values()]:
                if fact:
                    refs.extend(fact.get("evidence_refs", []))
        if form:
            for records in form["sections"].values():
                for record in records:
                    for fact in record["fields"].values():
                        refs.extend(fact.get("evidence_refs", []))
            refs = list({(r["evidence_id"], r["version"]): r for r in refs}.values())
        new_profile = save_artifact(
            db,
            job,
            "D03",
            {
                "facts": facts,
                "unknown_fields": [k for k, f in facts.items() if f["status"] != "stated"],
                "research_objects": objects,
                "resume_form": form,
                "document_metadata": target.content.get("document_metadata"),
            },
            application=application,
            source="manual",
            inherited=[target.source_mode, *target.inherited_source_modes],
            inputs=[artifact_ref(target)],
            allow_expired_inputs=True,
            evidence=refs,
        )
        if "name" in facts_to_change:
            name = facts_to_change["name"]
            application.name = (
                name.value
                if name.status == "stated"
                and isinstance(name.value, str)
                and len(name.value) <= 100
                else db.get(StoredFile, application.file_id).name
            )
        entry = audit(
            db,
            job,
            user.id,
            "profile.corrected",
            application_id=application.id,
            refs={
                "reason": body.reason,
                "artifact_ref": artifact_ref(new_profile),
                "generation": application.generation,
            },
        )
        return {
            "correction_id": entry.id,
            "application_id": application.id,
            "new_artifact_ref": artifact_ref(new_profile),
            "invalidated_artifact_refs": invalidated,
            "application_revision": application.revision,
            "requires_recompute": True,
            "external_actions": [],
            "blocked_task_ids": blocked_ids,
            "affected_delivery_ids": [],
            "created_at": aware(entry.created_at),
        }

    return execute(db, user, request, body.model_dump(), 201, action)


@router.post(
    "/applications/{application_id}/recompute", status_code=202, response_model=dto.TaskAccepted
)
def recompute(application_id: str, body: RecomputeInput, request: Request, db: Db, user: User):
    def action():
        application = get_application(db, user, application_id, lock=True)
        job = get_job(db, user, application.job_id)
        require_revision(application.revision, body.expected_revision)
        rule = db.get(RulePack, (job.id, application.rule_version))
        if rule_ref(rule) != body.rule_pack_ref.model_dump():
            raise DomainError("PRECONDITION_NOT_MET", "重算须使用当前关联绑定规则")
        correction = db.get(AuditEntry, body.correction_id)
        if (
            correction is None
            or correction.action != "profile.corrected"
            or correction.application_id != application.id
            or correction.refs["generation"] != application.generation
        ):
            raise DomainError("PRECONDITION_NOT_MET", "更正记录不属于当前版本")
        if body.target_steps != ["research", "screening"]:
            raise DomainError("PRECONDITION_NOT_MET", "D03 更正后须依次重算研究与初筛")
        d03 = latest(db, job.id, "D03", application.id)
        task = queue_step(db, job, application, "research", input_refs=[artifact_ref(d03)])
        application.stage = "research"
        application.gaps = []
        audit(
            db,
            job,
            user.id,
            "recompute.requested",
            application_id=application.id,
            refs={"correction_id": correction.id, "task_id": task.id},
        )
        return accepted(task)

    return execute(db, user, request, body.model_dump(), 202, action)


@router.post(
    "/applications/{application_id}/screening-review",
    status_code=201,
    response_model=dto.ScreeningReviewResult,
)
def review_screening(
    application_id: str, body: ScreeningReviewInput, request: Request, db: Db, user: User
):
    def action():
        application = get_application(db, user, application_id, lock=True)
        job = get_job(db, user, application.job_id)
        d06 = latest(db, job.id, "D06", application.id)
        if d06 is None or artifact_ref(d06) != body.expected_d06_ref.model_dump():
            raise DomainError("VERSION_CONFLICT", "请复核当前有效 D06")
        refs = [ref.model_dump() for ref in body.evidence_refs]
        validate_review_evidence(db, user, application, refs)
        downstream = list(
            db.scalars(
                select(Artifact).where(
                    Artifact.application_id == application.id,
                    Artifact.type.in_(["D07", "D08", "D09", "D10"]),
                    Artifact.status == "valid",
                )
            )
        )
        db.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.application_id == application.id,
                OutboxEvent.event_type == "screening.passed",
                OutboxEvent.status == "pending",
            )
            .values(status="invalidated")
        )
        for artifact in [d06, *downstream]:
            artifact.status = "expired"
        new_d06 = save_artifact(
            db,
            job,
            "D06",
            {
                **d06.content,
                "result": body.result,
                "review": {
                    "actor_id": user.id,
                    "reason": body.reason,
                    "original_ref": artifact_ref(d06),
                },
            },
            application=application,
            source="manual",
            inherited=[d06.source_mode, *d06.inherited_source_modes],
            inputs=[artifact_ref(d06)],
            allow_expired_inputs=True,
            evidence=refs,
        )
        application.screening_result = body.result
        application.stage = "outreach" if body.result == "passed" else "screening"
        application.revision += 1
        application.updated_at = utcnow()
        rule = db.get(RulePack, (job.id, application.rule_version))
        publish_handoff(db, job, application, rule, new_d06)
        entry = audit(
            db,
            job,
            user.id,
            "screening.reviewed",
            application_id=application.id,
            refs={
                "new_ref": artifact_ref(new_d06),
                "original_ref": artifact_ref(d06),
                "result": body.result,
                "reason": body.reason,
            },
        )
        db.add(
            OutboxEvent(
                organization_id=user.organization_id,
                application_id=application.id,
                event_type="intake.invalidated",
                dedup_key=f"review:{entry.id}",
                payload={
                    "event_id": entry.id,
                    "application_id": application.id,
                    "invalidated_refs": [artifact_ref(a) for a in [d06, *downstream]],
                    "required_action": "recheck_contact_and_delivery",
                },
            )
        )
        return {
            "application_id": application.id,
            "original_ref": artifact_ref(d06),
            "new_ref": artifact_ref(new_d06),
            "result": body.result,
            "existing_call_id": None,
            "reviewer_id": user.id,
            "reviewed_at": aware(entry.created_at),
            "business_dedup_key": f"application:{application.id}",
        }

    return execute(db, user, request, body.model_dump(), 201, action)
