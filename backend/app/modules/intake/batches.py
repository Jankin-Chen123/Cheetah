import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, File, Form, Request
from fastapi import UploadFile as FastAPIUploadFile
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.core import http_models as dto
from app.core.artifacts import get_job, require_application_file
from app.core.auth import Db, User
from app.core.errors import DomainError, not_found
from app.core.idempotency import execute
from app.core.models import Application, BatchItem, ResumeBatch, RulePack, StoredFile, Task, new_id
from app.core.tasks import enqueue
from app.modules.intake.analysis import parse_file
from app.modules.intake.router import PageNumber, PageSize
from app.modules.intake.schemas import ResumeBatchInput
from app.modules.intake.service import audit, check_mode, queue_step, require_revision
from app.modules.intake.views import (
    batch_item_view,
    batch_receipt,
    batch_view,
    current_batch_items,
    paginate,
)

router = APIRouter(tags=["resume-batches"])


async def receive_items(request: Request) -> tuple[list[dict], str, dict]:
    settings = request.app.state.settings
    limit = settings.batch_limit * settings.file_byte_limit + 100_000
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise DomainError("PAYLOAD_TOO_LARGE", "批次请求超过限制", 413)
        chunks.append(chunk)
    request._body = b"".join(chunks)
    content_type = request.headers.get("content-type", "").split(";")[0]
    if content_type == "application/json":
        try:
            body = ResumeBatchInput.model_validate_json(request._body)
        except ValidationError as exc:
            raise DomainError("VALIDATION_ERROR", "文本批次格式不正确", 422) from exc
        raw = body.model_dump(mode="json")
        items = [
            {
                "client_item_id": item.client_item_id,
                "name": item.name,
                "media_type": "text/plain",
                "data": item.text.replace("\r\n", "\n").replace("\r", "\n").strip().encode(),
                "is_text": True,
            }
            for item in body.items
        ]
        return items, body.execution_mode, raw
    if content_type != "multipart/form-data":
        raise DomainError("UNSUPPORTED_FILE_TYPE", "请选择 JSON 文本或 multipart 文件批次", 415)
    try:
        async with request.form(
            max_files=settings.batch_limit, max_fields=2, max_part_size=100_000
        ) as form:
            manifest = json.loads(str(form.get("manifest", "{}")))
            if not isinstance(manifest, dict) or set(manifest) - {"items", "execution_mode"}:
                raise ValueError("unsupported manifest fields")
            files, entries = form.getlist("files"), manifest.get("items", [])
            if (
                not files
                or len(files) != len(entries)
                or len(files) > settings.batch_limit
                or not all(isinstance(file, UploadFile) for file in files)
            ):
                raise ValueError("invalid file manifest")
            mode = manifest.get("execution_mode", "live")
            if mode not in {"live", "mock"}:
                raise ValueError("invalid mode")
            items = []
            for file, entry in zip(files, entries, strict=True):
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"client_item_id", "filename"}
                    or not isinstance(entry["client_item_id"], str)
                    or not 1 <= len(entry["client_item_id"]) <= 128
                    or entry["filename"] != file.filename
                    or not 1 <= len(file.filename or "") <= 200
                ):
                    raise ValueError("invalid entry")
                data = await file.read(settings.file_byte_limit + 1)
                items.append(
                    {
                        "client_item_id": entry["client_item_id"],
                        "name": file.filename,
                        "media_type": file.content_type or "",
                        "data": data,
                        "is_text": False,
                    }
                )
            raw = {
                "manifest": manifest,
                "files": [
                    {
                        "name": item["name"],
                        "media_type": item["media_type"],
                        "hash": hashlib.sha256(item["data"]).hexdigest(),
                    }
                    for item in items
                ],
            }
            return items, mode, raw
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError("VALIDATION_ERROR", "文件清单格式不正确", 422) from exc


def accept_item(db, job, rule, settings, mode, batch, item, *, replaces_item_id=None):
    record = BatchItem(
        batch_id=batch.id,
        client_item_id=item["client_item_id"],
        name=item["name"],
        disposition="invalid",
    )
    db.add(record)
    record.replaces_item_id = replaces_item_id
    try:
        text = parse_file(
            "resume.txt" if item["is_text"] else item["name"],
            item["media_type"],
            item["data"],
            settings,
        )
    except DomainError as exc:
        record.error_code = exc.code
        return record
    material_hash = hashlib.sha256(item["data"]).hexdigest()
    existing = db.scalar(
        select(Application).where(
            Application.job_id == job.id, Application.material_hash == material_hash
        )
    )
    if existing:
        try:
            if existing.status != "active" or existing.organization_id != job.organization_id:
                raise DomainError("PRECONDITION_NOT_MET", "已有材料不可复用")
            require_application_file(db, existing)
        except DomainError:
            record.error_code = "PRECONDITION_NOT_MET"
            return record
        record.disposition, record.application_id = "duplicate", existing.id
        original = db.scalar(
            select(Task)
            .where(Task.application_id == existing.id, Task.kind == "resume_parse")
            .order_by(Task.created_at)
        )
        record.task_id = original.id if original else None
        original_item = db.scalar(
            select(BatchItem)
            .where(BatchItem.application_id == existing.id, BatchItem.disposition == "accepted")
            .order_by(BatchItem.created_at)
        )
        record.duplicate_of_item_id = original_item.id if original_item else None
        return record
    application_id, file_id = new_id(), new_id()
    application = Application(
        id=application_id,
        organization_id=job.organization_id,
        job_id=job.id,
        name=item["name"],
        material_text=text,
        material_hash=material_hash,
        file_id=file_id,
        rule_version=rule.version,
        execution_mode=mode,
    )
    db.add(application)
    db.add(
        StoredFile(
            id=file_id,
            organization_id=job.organization_id,
            job_id=job.id,
            application_id=application_id,
            name=item["name"],
            media_type=item["media_type"],
            data=item["data"],
            sha256=material_hash,
        )
    )
    db.flush()
    task = queue_step(db, job, application, "resume_parse")
    record.disposition, record.application_id, record.task_id = (
        "accepted",
        application.id,
        task.id,
    )
    record.replaces_item_id = replaces_item_id
    return record


@router.post("/jobs/{job_id}/resume-batches", status_code=202, response_model=dto.BatchAccepted)
async def import_batch(job_id: str, request: Request, db: Db, user: User):
    get_job(db, user, job_id)
    items, mode, raw = await receive_items(request)

    def action():
        settings = request.app.state.settings
        check_mode(settings, mode)
        job = get_job(db, user, job_id, lock=True)
        if job.status != "active":
            raise DomainError("PRECONDITION_NOT_MET", "岗位未启用")
        if job.published_version is None:
            raise DomainError("RULES_NOT_PUBLISHED", "请先确认发布规则")
        rule = db.get(RulePack, (job.id, job.published_version))
        if mode == "live" and rule.is_test_rule:
            check_mode(request.app.state.settings, "mock")
        if len(items) > settings.batch_limit or len({i["client_item_id"] for i in items}) != len(
            items
        ):
            raise DomainError("VALIDATION_ERROR", "批次数量超限或 client_item_id 重复", 422)
        batch_id = new_id()
        parent = enqueue(
            db,
            organization_id=user.organization_id,
            job_id=job.id,
            kind="batch",
            dedup_key=f"batch:{batch_id}",
            payload={"batch_id": batch_id},
        )
        batch = ResumeBatch(
            id=batch_id,
            organization_id=user.organization_id,
            job_id=job.id,
            task_id=parent.id,
            rule_version=rule.version,
            execution_mode=mode,
        )
        db.add(batch)
        for item in items:
            accept_item(db, job, rule, settings, mode, batch, item)
        db.flush()
        from app.worker import refresh_batches

        refresh_batches(db, parent.id)
        # Newly accepted children have not run yet; invalid-only batches are terminal.
        records = list(db.scalars(select(BatchItem).where(BatchItem.batch_id == batch.id)))
        if not any(item.task_id for item in records):
            parent.status, parent.error_code = "failed", "INVALID_BATCH"
        elif all(item.disposition == "duplicate" for item in records):
            applications = [db.get(Application, item.application_id) for item in records]
            parent.status = (
                "completed"
                if all(a.screening_result != "pending" for a in applications)
                else "running"
            )
        else:
            parent.status = "running"
        audit(db, job, user.id, "batch.created", refs={"batch_id": batch.id})
        return batch_receipt(db, batch)

    return await run_in_threadpool(execute, db, user, request, raw, 202, action)


@router.get("/batches/{batch_id}", response_model=dto.Batch)
def read_batch(batch_id: str, db: Db, user: User):
    batch = db.get(ResumeBatch, batch_id)
    if batch is None:
        raise not_found()
    get_job(db, user, batch.job_id)
    return batch_view(db, batch)


@router.get("/batches/{batch_id}/items", response_model=dto.BatchItemPage)
def list_batch_items(
    batch_id: str, db: Db, user: User, page: PageNumber = 1, page_size: PageSize = 20
):
    read_batch(batch_id, db, user)
    return paginate(
        db,
        current_batch_items(db, batch_id).order_by(BatchItem.created_at, BatchItem.id),
        page,
        page_size,
        lambda item: batch_item_view(db, item),
    )


@router.post(
    "/batches/{batch_id}/items/{item_id}/replace", status_code=201, response_model=dto.BatchItem
)
async def replace_item(
    batch_id: str,
    item_id: str,
    request: Request,
    db: Db,
    user: User,
    expected_revision: Annotated[int, Form(ge=1)],
    file: Annotated[FastAPIUploadFile, File()],
):
    batch = db.get(ResumeBatch, batch_id)
    if batch is None:
        raise not_found()
    get_job(db, user, batch.job_id)
    data = await file.read(request.app.state.settings.file_byte_limit + 1)
    if not file.filename or len(file.filename) > 200:
        raise DomainError("VALIDATION_ERROR", "文件名不合法", 422)
    body = {
        "expected_revision": expected_revision,
        "name": file.filename,
        "media_type": file.content_type,
        "hash": hashlib.sha256(data).hexdigest(),
    }

    def action():
        job = get_job(db, user, batch.job_id, lock=True)
        old = db.get(BatchItem, item_id)
        if old is None or old.batch_id != batch.id:
            raise not_found()
        require_revision(old.revision, expected_revision)
        if (
            old.disposition != "invalid"
            or db.scalar(select(BatchItem).where(BatchItem.replaces_item_id == old.id))
            or job.status != "active"
        ):
            raise DomainError("PRECONDITION_NOT_MET", "仅可替换尚未被替换的校验失败材料")
        settings = request.app.state.settings
        check_mode(settings, batch.execution_mode)
        rule = db.get(RulePack, (job.id, batch.rule_version))
        record = accept_item(
            db,
            job,
            rule,
            settings,
            batch.execution_mode,
            batch,
            {
                "client_item_id": old.client_item_id,
                "name": file.filename,
                "data": data,
                "media_type": file.content_type or "",
                "is_text": False,
            },
            replaces_item_id=old.id,
        )
        old.revision += 1
        db.flush()
        from app.worker import refresh_batches

        refresh_batches(db, batch.task_id)
        audit(
            db,
            job,
            user.id,
            "batch.item_replaced",
            refs={"item_id": record.id, "old_item_id": old.id},
        )
        return batch_item_view(db, record)

    return await run_in_threadpool(execute, db, user, request, body, 201, action)
