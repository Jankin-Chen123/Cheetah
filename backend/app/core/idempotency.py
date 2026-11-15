import hashlib
import json
import re
from collections.abc import Callable
from datetime import timedelta

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.auth import digest
from app.core.errors import DomainError
from app.core.models import Idempotency, Identity, aware, utcnow


def response_headers(request: Request, payload: dict, status_code: int) -> dict[str, str]:
    if status_code == 201 and request.url.path == "/api/v1/jobs":
        return {"Location": f"/api/v1/jobs/{payload['id']}"}
    if status_code == 202 and payload.get("task_id"):
        return {"Location": f"/api/v1/tasks/{payload['task_id']}"}
    return {}


def execute(
    db: Session,
    user: Identity,
    request: Request,
    body: dict,
    status_code: int,
    action: Callable[[], dict],
) -> JSONResponse:
    key = request.headers.get("Idempotency-Key", "")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", key) is None:
        raise DomainError("VALIDATION_ERROR", "请提供 8—128 位 Idempotency-Key", 422)
    scope = digest(f"{user.organization_id}:{user.id}:{request.method}:{request.url.path}:{key}")
    request_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if db.bind.dialect.name == "postgresql":
        # Transaction-scoped lock covers in-flight duplicates before a record exists.
        lock_key = int(scope[:15], 16)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    record = db.scalar(select(Idempotency).where(Idempotency.scope == scope))
    if record and aware(record.expires_at) <= utcnow():
        db.delete(record)
        db.flush()
        record = None
    if record:
        if record.request_hash != request_hash:
            raise DomainError("IDEMPOTENCY_KEY_REUSED", "同一请求标识已用于不同内容")
        from app.core.artifacts import get_application, get_job
        from app.core.models import ResumeBatch

        saved = record.response
        if saved.get("resource_type") == "audio_transcription":
            from app.modules.intake.audio import get_audio

            get_audio(db, user, saved["resource_id"])
        if saved.get("resource_type") == "talent" or request.url.path.startswith(
            "/api/v1/talents/"
        ):
            from app.modules.intake.talents import get_talent

            get_talent(db, user, saved.get("resource_id") or saved["id"])
        if request.url.path == "/api/v1/talent-imports":
            from app.modules.intake.talents import get_talent

            for item in saved.get("items", []):
                if item.get("talent_id"):
                    get_talent(db, user, item["talent_id"])
        if saved.get("resource_type") == "application":
            get_application(db, user, saved["resource_id"])
        elif saved.get("resource_type") == "job":
            get_job(db, user, saved["resource_id"])
        elif saved.get("application_id"):
            get_application(db, user, saved["application_id"])
        elif saved.get("job_id"):
            get_job(db, user, saved["job_id"])
        elif saved.get("batch_id"):
            batch = db.get(ResumeBatch, saved["batch_id"])
            get_job(db, user, batch.job_id)
        elif request.url.path == "/api/v1/jobs":
            get_job(db, user, saved["id"])
        return JSONResponse(
            record.response,
            record.status_code,
            headers={
                **response_headers(request, record.response, record.status_code),
                "Idempotency-Replayed": "true",
            },
        )
    result = action()
    model = request.scope["route"].response_model
    payload = jsonable_encoder(model.model_validate(result) if model else result)
    db.add(
        Idempotency(
            scope=scope,
            request_hash=request_hash,
            status_code=status_code,
            response=payload,
            expires_at=utcnow() + timedelta(hours=request.app.state.settings.idempotency_hours),
        )
    )
    db.flush()
    return JSONResponse(
        payload, status_code, headers=response_headers(request, payload, status_code)
    )
