"""Private persisted audio recognition; ASR output remains reviewable material."""

import hashlib
import io
import wave
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth import Db, User
from app.core.errors import DomainError, not_found
from app.core.idempotency import execute
from app.core.models import AudioTranscription, Identity, aware, utcnow
from app.integrations.search import public_source_url
from app.integrations.voice.file_asr import FileAsrError, recognize, standard_request
from app.modules.intake.talents import lock_owner

router = APIRouter(tags=["file-asr"])
RETRY_CODES = {
    "ASR_RESOURCE_NOT_GRANTED",
    "ASR_NOT_CONFIGURED",
    "ASR_PROVIDER_REJECTED",
    "ASR_RESPONSE_INVALID",
    "ASR_RESULT_TOO_LARGE",
}
ERRORS = {
    "ASR_RESOURCE_NOT_GRANTED": "当前密钥未获所选识别接口权限，请核对标准版与极速版的开通范围。",
    "ASR_NOT_CONFIGURED": "录音文件识别服务尚未配置。",
    "ASR_EXTERNAL_RESULT_UNKNOWN": "识别请求结果尚未核对，材料已保存，不会自动重复调用。",
    "ASR_NO_SPEECH": "没有识别到有效语音，请检查录音是否静音。",
    "ASR_INVALID_AUDIO": "录音文件无法解析，请检查文件是否完整。",
    "ASR_UNSUPPORTED_FORMAT": "语音服务不支持此音频编码，请改用 WAV、MP3 或 OGG OPUS。",
    "ASR_TEXT_TOO_LONG": "转写超过30,000字，请拆分录音后识别。",
    "ASR_DURATION_LIMIT": "录音超过两小时，请拆分后识别。",
}


class AudioSegment(BaseModel):
    text: str
    start_ms: int
    end_ms: int


class AudioTranscriptionView(BaseModel):
    id: str
    resource_type: Literal["audio_transcription"] = "audio_transcription"
    resource_id: str
    status: Literal["queued", "running", "waiting_provider", "completed", "failed", "reconciling"]
    revision: int
    filename: str
    transcript: str | None
    segments: list[AudioSegment]
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    source_mode: Literal["live"] = "live"


class AudioRetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class AudioUrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_url: str = Field(min_length=1, max_length=2048, repr=False)
    audio_format: Literal["wav", "mp3", "ogg", "aac", "m4a", "amr", "spx"]


@router.post(
    "/audio-transcriptions/from-url", response_model=AudioTranscriptionView, status_code=202
)
def recognize_url(body: AudioUrlInput, request: Request, db: Db, user: User):
    if not configured(request.app.state.settings):
        raise DomainError("ASR_NOT_CONFIGURED", ERRORS["ASR_NOT_CONFIGURED"], 503)
    if not public_source_url(body.audio_url, []) or urlsplit(body.audio_url).scheme != "https":
        raise DomainError(
            "ASR_URL_INVALID",
            "请使用无需登录的公网 HTTPS 音频地址，不支持内网或含密钥的网址。",
            422,
        )
    digest = hashlib.sha256((body.audio_format + ":" + body.audio_url).encode()).hexdigest()

    def action():
        lock_owner(db, user.id)
        existing = db.scalar(
            select(AudioTranscription).where(
                AudioTranscription.owner_id == user.id, AudioTranscription.audio_hash == digest
            )
        )
        if existing:
            return view(existing)
        require_budget(db, user, request.app.state.settings)
        item = AudioTranscription(
            organization_id=user.organization_id,
            owner_id=user.id,
            filename="远程录音." + body.audio_format,
            audio_format="url",
            data=body.audio_url.encode(),
            audio_hash=digest,
        )
        db.add(item)
        db.flush()
        return view(item)

    return execute(db, user, request, {"url_hash": digest}, 202, action)


def get_audio(db, user, audio_id, *, lock=False):
    query = select(AudioTranscription).where(
        AudioTranscription.id == audio_id,
        AudioTranscription.owner_id == user.id,
        AudioTranscription.organization_id == user.organization_id,
    )
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise not_found()
    return item


def view(item):
    return {
        "id": item.id,
        "resource_id": item.id,
        "status": item.status,
        "revision": item.revision,
        "filename": item.filename,
        "transcript": item.transcript,
        "segments": item.segments,
        "duration_ms": item.duration_ms,
        "error_code": item.error_code,
        "error_message": ERRORS.get(item.error_code, "识别未完成，请核对服务权限、录音与后台任务。")
        if item.error_code
        else None,
        "retryable": item.status == "failed"
        and item.error_code in RETRY_CODES
        and item.attempts < 3,
    }


def configured(settings):
    return settings.file_asr_provider == "volcengine" and bool(settings.volc_speech_api_key)


def require_budget(db, user, settings, *, claimed=False):
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(
        select(func.coalesce(func.sum(AudioTranscription.attempts), 0)).where(
            AudioTranscription.owner_id == user.id,
            or_(AudioTranscription.created_at >= today, AudioTranscription.started_at >= today),
        )
    )
    queued = (
        0
        if claimed
        else db.scalar(
            select(func.count())
            .select_from(AudioTranscription)
            .where(AudioTranscription.owner_id == user.id, AudioTranscription.status == "queued")
        )
    )
    if used + queued >= settings.file_asr_daily_limit:
        raise DomainError("ASR_DAILY_LIMIT", "今日录音识别次数已达上限，请稍后处理。", 429)


def validate_audio(data, filename):
    extension = Path(filename).suffix.lower()
    valid = {
        ".wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
        ".mp3": data.startswith(b"ID3")
        or (len(data) > 2 and data[0] == 255 and data[1] & 0xE0 == 0xE0),
        ".ogg": data.startswith(b"OggS"),
    }
    if not valid.get(extension):
        raise DomainError(
            "ASR_UNSUPPORTED_FORMAT",
            "请选择 WAV、MP3 或 OGG OPUS 音频，文件内容须与格式一致。",
            422,
        )
    if extension == ".wav":
        try:
            with wave.open(io.BytesIO(data)) as audio:
                if not audio.getnframes() or audio.getnframes() / audio.getframerate() > 7200:
                    raise DomainError("ASR_DURATION_LIMIT", "请选择非空且不超过两小时的录音。", 422)
        except (wave.Error, EOFError):
            raise DomainError("ASR_INVALID_AUDIO", "WAV 文件不完整或编码不受支持。", 422) from None
    return extension[1:]


@router.post("/audio-transcriptions", response_model=AudioTranscriptionView, status_code=202)
async def upload_audio(request: Request, db: Db, user: User, file: Annotated[UploadFile, File()]):
    settings = request.app.state.settings
    if not configured(settings):
        raise DomainError("ASR_NOT_CONFIGURED", ERRORS["ASR_NOT_CONFIGURED"], 503)
    data = await file.read(settings.file_asr_byte_limit + 1)
    await file.close()
    if not data or len(data) > settings.file_asr_byte_limit:
        raise DomainError("ASR_FILE_SIZE_LIMIT", "录音为空或超过当前服务大小上限。", 422)
    name = (file.filename or "audio").replace("\\", "/").split("/")[-1][:200]
    audio_format = validate_audio(data, name)
    digest = hashlib.sha256(data).hexdigest()

    def action():
        lock_owner(db, user.id)
        existing = db.scalar(
            select(AudioTranscription).where(
                AudioTranscription.owner_id == user.id, AudioTranscription.audio_hash == digest
            )
        )
        if existing:
            return view(existing)
        require_budget(db, user, settings)
        item = AudioTranscription(
            organization_id=user.organization_id,
            owner_id=user.id,
            filename=name,
            audio_format=audio_format,
            data=data,
            audio_hash=digest,
        )
        db.add(item)
        db.flush()
        return view(item)

    return execute(db, user, request, {"sha256": digest, "filename": name}, 202, action)


@router.get("/audio-transcriptions/{audio_id}", response_model=AudioTranscriptionView)
def read_audio(audio_id: str, db: Db, user: User):
    return view(get_audio(db, user, audio_id))


@router.post(
    "/audio-transcriptions/{audio_id}/retry", response_model=AudioTranscriptionView, status_code=202
)
def retry_audio(audio_id: str, body: AudioRetryInput, request: Request, db: Db, user: User):
    def action():
        lock_owner(db, user.id)
        item = get_audio(db, user, audio_id, lock=True)
        if item.revision != body.expected_revision or not view(item)["retryable"]:
            raise DomainError(
                "ASR_NOT_RETRYABLE", "识别结果未知、状态已变化或次数已用尽，不能重试。"
            )
        if not configured(request.app.state.settings):
            raise DomainError("ASR_NOT_CONFIGURED", ERRORS["ASR_NOT_CONFIGURED"], 503)
        require_budget(db, user, request.app.state.settings)
        item.status, item.error_code = "queued", None
        item.provider_request_id = None
        item.started_at = None
        item.finished_at = None
        item.revision += 1
        return view(item)

    return execute(db, user, request, body.model_dump(), 202, action)


def run_audio_once(settings, engine):
    with Session(engine) as db, db.begin():
        cutoff = utcnow() - timedelta(seconds=settings.file_asr_timeout_seconds + 60)
        for stale in db.scalars(
            select(AudioTranscription)
            .where(AudioTranscription.status == "running", AudioTranscription.started_at < cutoff)
            .with_for_update(skip_locked=True)
        ):
            stale.status, stale.error_code = "reconciling", "ASR_EXTERNAL_RESULT_UNKNOWN"
            stale.finished_at = utcnow()
            stale.revision += 1
    with Session(engine) as db, db.begin():
        due = utcnow() - timedelta(seconds=5)
        query = (
            select(AudioTranscription)
            .where(
                or_(
                    AudioTranscription.status == "queued",
                    (AudioTranscription.audio_format == "url")
                    & AudioTranscription.status.in_(["waiting_provider", "reconciling"])
                    & (AudioTranscription.finished_at < due),
                )
            )
            .order_by(AudioTranscription.created_at)
            .limit(1)
        )
        candidate = db.execute(
            query.with_only_columns(AudioTranscription.id, AudioTranscription.owner_id)
        ).first()
        if candidate is None:
            return False
        # Match upload/retry lock order: owner first, then receipt, then reserve a call.
        lock_owner(db, candidate.owner_id)
        item = db.scalar(
            query.where(AudioTranscription.id == candidate.id).with_for_update(skip_locked=True)
        )
        if item is None:
            return False
        owner = db.get(Identity, item.owner_id)
        if not owner or not owner.enabled or owner.organization_id != item.organization_id:
            item.status, item.error_code = "failed", "PERMISSION_DENIED"
            item.revision += 1
            return True
        querying = item.audio_format == "url" and item.provider_request_id is not None
        if not querying:
            try:
                require_budget(db, owner, settings, claimed=True)
            except DomainError:
                item.status, item.error_code = "failed", "ASR_DAILY_LIMIT"
                item.revision += 1
                return True
        if querying and utcnow() - aware(item.created_at) > timedelta(hours=24):
            item.status, item.error_code = "failed", "ASR_EXTERNAL_RESULT_UNKNOWN"
            item.revision += 1
            return True
        item.status, item.started_at = "running", utcnow()
        if not querying:
            item.attempts += 1
            item.provider_request_id = str(uuid4())
        item.revision += 1
        audio_id, request_id, data, owner_id = (
            item.id,
            item.provider_request_id,
            item.data,
            owner.id,
        )
        is_url, audio_format = item.audio_format == "url", Path(item.filename).suffix[1:]
    try:
        result = (
            standard_request(
                settings,
                request_id,
                **({} if querying else {"audio_url": data.decode(), "audio_format": audio_format}),
            )
            if is_url
            else recognize(settings, data, request_id, owner_id)
        )
        failure = None
    except FileAsrError as error:
        result, failure = None, error
    with Session(engine) as db, db.begin():
        item = db.get(AudioTranscription, audio_id, with_for_update=True)
        if item.provider_request_id != request_id:
            return True
        if failure:
            item.status = "reconciling" if failure.uncertain else "failed"
            item.error_code = failure.code
        elif result is None:
            item.status, item.error_code = "waiting_provider", None
        else:
            item.status, item.error_code = "completed", None
            item.transcript, item.segments, item.duration_ms = (
                result["transcript"],
                result["segments"],
                result["duration_ms"],
            )
        item.finished_at = utcnow()
        item.revision += 1
    return True
