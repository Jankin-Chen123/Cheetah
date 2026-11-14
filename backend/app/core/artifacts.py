"""Shared artifact/evidence access. Consumers must supply the authenticated identity."""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, not_found
from app.core.models import (
    Application,
    Artifact,
    Evidence,
    Identity,
    IntakeJob,
    RulePack,
    StoredFile,
    aware,
    new_id,
)


def get_job(db: Session, user: Identity, job_id: str, *, lock: bool = False) -> IntakeJob:
    query = select(IntakeJob).where(
        IntakeJob.id == job_id,
        IntakeJob.organization_id == user.organization_id,
        IntakeJob.owner_id == user.id,
    )
    if lock:
        query = query.with_for_update()
    job = db.scalar(query.execution_options(populate_existing=True))
    if job is None:
        raise not_found()
    return job


def get_application(
    db: Session, user: Identity, application_id: str, *, lock: bool = False
) -> Application:
    application = db.get(Application, application_id)
    if application is None:
        raise not_found()
    job = get_job(db, user, application.job_id, lock=lock)
    if lock:
        db.refresh(application)
    if application.status != "active" or application.organization_id != job.organization_id:
        raise not_found()
    require_application_file(db, application)
    return application


def require_application_file(db: Session, application: Application) -> StoredFile:
    file = db.get(StoredFile, application.file_id)
    if (
        file is None
        or file.status != "valid"
        or file.application_id != application.id
        or file.job_id != application.job_id
        or file.organization_id != application.organization_id
    ):
        raise not_found()
    return file


def visible_application_file():
    return exists(
        select(StoredFile.id).where(
            StoredFile.id == Application.file_id,
            StoredFile.application_id == Application.id,
            StoredFile.job_id == Application.job_id,
            StoredFile.organization_id == Application.organization_id,
            StoredFile.status == "valid",
        )
    )


def artifact_ref(artifact: Artifact) -> dict:
    return {"artifact_id": artifact.artifact_id, "version": artifact.version}


def evidence_ref(evidence: Evidence) -> dict:
    return {"evidence_id": evidence.evidence_id, "version": evidence.version}


def merge_source_modes(*sources: dict) -> dict:
    result = {key: None for key in ("candidate_material", "model", "research", "phone")}
    for key in result:
        values = {source.get(key) for source in sources} - {None}
        result[key] = next((mode for mode in ("mock", "live", "manual") if mode in values), None)
    return result


def latest(
    db: Session,
    job_id: str,
    kind: str,
    application_id: str | None = None,
    *,
    valid_only: bool = True,
) -> Artifact | None:
    query = select(Artifact).where(
        Artifact.job_id == job_id,
        Artifact.application_id == application_id,
        Artifact.type == kind,
    )
    if valid_only:
        query = query.where(Artifact.status == "valid")
    return db.scalar(query.order_by(Artifact.version.desc()))


def save_artifact(
    db: Session,
    job: IntakeJob,
    kind: str,
    content: dict,
    *,
    application: Application | None = None,
    source: str,
    inherited: list[str] | None = None,
    inputs: list | None = None,
    evidence: list | None = None,
    source_modes: dict | None = None,
    allow_expired_inputs: bool = False,
) -> Artifact:
    # Caller holds the job row lock. Versions are stable within each logical D artifact.
    previous = latest(db, job.id, kind, application.id if application else None, valid_only=False)
    from app.modules.intake.content import validate_content

    upstream = [
        db.get(Artifact, (ref.get("artifact_id", ref.get("id")), ref["version"]))
        for ref in inputs or []
        if "artifact_id" in ref or ref.get("kind") == "artifact"
    ]
    if application:
        if application.job_id != job.id or application.organization_id != job.organization_id:
            raise not_found()
        require_application_file(db, application)
    for item in upstream:
        if item is None:
            raise DomainError("PRECONDITION_NOT_MET", "产物输入引用不存在")
        if (
            item.job_id != job.id
            or item.organization_id != job.organization_id
            or item.application_id not in {None, application.id if application else None}
        ):
            raise not_found()
    for item in upstream:
        if item.status != "valid" and not (allow_expired_inputs and item.status == "expired"):
            raise DomainError("PRECONDITION_NOT_MET", "产物输入已经失效或受限")
    for ref in evidence or []:
        item = db.get(Evidence, (ref["evidence_id"], ref["version"]))
        if (
            item is None
            or item.status != "valid"
            or item.job_id != job.id
            or item.organization_id != job.organization_id
            or item.application_id not in {None, application.id if application else None}
        ):
            raise DomainError("PRECONDITION_NOT_MET", "证据引用不属于当前有效对象")
    stages = merge_source_modes(
        *(item.source_modes for item in upstream if item), source_modes or {}
    )
    if application:
        stages["candidate_material"] = "mock" if application.execution_mode == "mock" else "manual"
    if kind in {"D01", "D02", "D03"} and source in {"live", "mock"}:
        stages = merge_source_modes(stages, {"model": source})
    if kind == "D04":
        stages["research"] = source if content.get("status") != "not_executed" else None
    inherited_modes = set(inherited or [])
    for upstream_artifact in upstream:
        if upstream_artifact:
            inherited_modes.update(
                [upstream_artifact.source_mode, *upstream_artifact.inherited_source_modes]
            )
    inherited_modes.update(mode for mode in stages.values() if mode is not None and mode != source)

    artifact = Artifact(
        artifact_id=previous.artifact_id if previous else new_id(),
        version=previous.version + 1 if previous else 1,
        organization_id=job.organization_id,
        job_id=job.id,
        application_id=application.id if application else None,
        type=kind,
        content=validate_content(kind, content),
        source_mode=source,
        inherited_source_modes=sorted(inherited_modes),
        source_modes=stages,
        input_refs=[
            {"kind": "artifact", "id": ref["artifact_id"], "version": ref["version"]}
            if "artifact_id" in ref
            else ref
            for ref in inputs or []
        ],
        evidence_refs=evidence or [],
        rule_pack_version=application.rule_version if application else None,
    )
    db.add(artifact)
    db.flush()
    return artifact


def get_artifact(db: Session, user: Identity, ref: dict, *, valid: bool = False) -> Artifact:
    artifact = db.get(Artifact, (ref["artifact_id"], ref["version"]))
    if artifact is None:
        raise not_found()
    get_job(db, user, artifact.job_id)
    if artifact.application_id:
        application = get_application(db, user, artifact.application_id)
        if application.status != "active":
            raise not_found()
    if artifact.status == "restricted" or (valid and artifact.status != "valid"):
        raise not_found()
    return artifact


def get_evidence(db: Session, user: Identity, ref: dict) -> Evidence:
    evidence = db.get(Evidence, (ref["evidence_id"], ref["version"]))
    if evidence is None or evidence.status == "restricted":
        raise not_found()
    get_job(db, user, evidence.job_id)
    if evidence.application_id:
        application = get_application(db, user, evidence.application_id)
        if application.status != "active":
            raise not_found()
    return evidence


def provenance(source: str, inherited: list[str] | None = None, stages: dict | None = None) -> dict:
    modes = (set(inherited or []) | {source} | set((stages or {}).values())) - {None}
    return {
        "source_mode": source,
        "inherited_source_modes": sorted(modes - {source}),
        "fixture_only": "mock" in modes,
        "source_modes": stages
        or {"candidate_material": None, "model": None, "research": None, "phone": None},
    }


def input_artifact(db: Session, artifact: Artifact, kind: str) -> Artifact | None:
    pending, seen = [artifact], set()
    while pending and len(seen) < 100:
        current = pending.pop(0)
        key = (current.artifact_id, current.version)
        if key in seen:
            continue
        seen.add(key)
        if current.type == kind:
            return current
        for ref in current.input_refs:
            if ref.get("kind") != "artifact":
                continue
            item = db.get(Artifact, (ref["id"], ref["version"]))
            if item and item.job_id == artifact.job_id and item.status != "restricted":
                pending.append(item)
    return None


def artifact_view(db: Session, artifact: Artifact) -> dict:
    import json

    from app.core.http_models import Artifact as ArtifactDTO
    from app.modules.intake.a03_report import render_report
    from app.modules.intake.form_reports import (
        render_interview,
        render_job,
        render_resume,
        render_screening,
    )

    application = db.get(Application, artifact.application_id) if artifact.application_id else None
    rule = (
        db.get(RulePack, (artifact.job_id, artifact.rule_pack_version))
        if artifact.rule_pack_version
        else None
    )
    inputs = []
    for ref in artifact.input_refs:
        if "artifact_id" in ref:
            inputs.append({"kind": "artifact", "id": ref["artifact_id"], "version": ref["version"]})
        elif "kind" in ref:
            inputs.append(ref)
    stages = merge_source_modes(artifact.source_modes)
    rule_ref = (
        {
            "rule_pack_id": rule.rule_pack_id,
            "version": rule.version,
            "publication_status": "published",
            "is_test_rule": rule.is_test_rule,
        }
        if rule
        else None
    )
    markdown = None
    if artifact.type == "D01" and artifact.content.get("job_form"):
        markdown = render_job(artifact.content)
    elif artifact.type == "D02":
        d01 = input_artifact(db, artifact, "D01")
        context = (
            {
                key: value.get("value")
                for key, value in (d01.content.get("job_form") or {}).get("fields", {}).items()
            }
            if d01
            else {}
        )
        markdown = render_interview(artifact.content, context)
    elif artifact.type == "D03" and artifact.content.get("resume_form"):
        markdown = render_resume(artifact.content)
    elif artifact.type in {"D05", "D06"}:
        d05 = input_artifact(db, artifact, "D05")
        # A D05 view must not pull an unrelated latest report after a correction.
        d06 = (
            artifact
            if artifact.type == "D06"
            else next(
                (
                    item
                    for item in db.scalars(
                        select(Artifact)
                        .where(
                            Artifact.application_id == artifact.application_id,
                            Artifact.type == "D06",
                        )
                        .order_by(Artifact.version.desc())
                    )
                    if input_artifact(db, item, "D05") is artifact
                ),
                None,
            )
        )
        if d05 and d06 and d06.content.get("screening_rubric"):
            markdown = render_screening(d05.content, d06.content)
    payload = {
        **artifact_ref(artifact),
        "type": artifact.type,
        "status": artifact.status,
        "job_id": artifact.job_id,
        "application_id": artifact.application_id,
        "structured_content": artifact.content,
        "content_markdown": (
            markdown
            if markdown is not None
            else render_report(artifact.content["report"])
            if artifact.type == "D04" and artifact.content.get("report")
            else "```json\n" + json.dumps(artifact.content, ensure_ascii=False, indent=2) + "\n```"
        ),
        "workflow_id": application.workflow_id if application else artifact.job_id,
        "step": artifact.type,
        "input_refs": inputs,
        "rule_pack_ref": rule_ref,
        "evidence_refs": artifact.evidence_refs,
        "provenance": provenance(artifact.source_mode, artifact.inherited_source_modes, stages),
        "generated_at": aware(artifact.created_at),
        "generator": {
            "kind": "research_adapter"
            if artifact.type == "D04" and artifact.content.get("status") != "not_executed"
            else "model"
            if artifact.source_mode == "live"
            else "parser"
            if artifact.source_mode == "mock" and artifact.type in {"D01", "D02", "D03"}
            else "manual",
            "model": None,
            "method_version": "intake-specs-v2"
            if any(
                artifact.content.get(key) for key in ("job_form", "resume_form", "screening_rubric")
            )
            else "intake-v1",
        },
        "unknowns": artifact.content.get("unknown_fields", artifact.content.get("gaps", [])),
        "validation": {"passed": True, "issues": []},
        "correction_of_ref": artifact.content.get("review", {}).get("original_ref"),
        "superseded_by_ref": {"artifact_id": artifact.artifact_id, "version": artifact.version + 1}
        if db.get(Artifact, (artifact.artifact_id, artifact.version + 1))
        else None,
    }
    return ArtifactDTO.model_validate(payload).model_dump(mode="json")
