import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import http_models as dto
from app.core.database import get_db, get_engine
from app.core.errors import DomainError
from app.core.models import Identity, LoginSession, LoginThrottle, aware, new_id, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "cheetah_session"


def browser_db(request: Request):
    if request.url.path not in {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    } and not request.cookies.get(COOKIE):
        raise DomainError("AUTH_REQUIRED", "请先登录", 401)
    yield from get_db(request)


Db = Annotated[Session, Depends(browser_db, scope="function")]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return f"scrypt${salt}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def check_origin(request: Request):
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise DomainError("CSRF_INVALID", "请求来源不允许", 403)


def current_user(request: Request, db: Db) -> Identity:
    raw = request.cookies.get(COOKIE, "")
    login = db.get(LoginSession, digest(raw)) if raw else None
    if login is None or aware(login.expires_at) <= utcnow():
        raise DomainError("AUTH_REQUIRED", "请先登录", 401)
    user = db.get(Identity, login.user_id)
    if user is None or not user.enabled:
        raise DomainError("AUTH_REQUIRED", "请先登录", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        csrf = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(csrf, digest("csrf:" + raw)):
            raise DomainError("CSRF_INVALID", "会话校验失败", 403)
    request.state.identity = user.id
    return user


User = Annotated[Identity, Depends(current_user)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    display_name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    password: str = Field(min_length=12, max_length=128, repr=False)


def session_view(request: Request, user: Identity, login: LoginSession, raw: str):
    settings = request.app.state.settings
    return {
        "user": {"id": user.id, "display_name": user.display_name},
        "organization": {"id": user.organization_id, "name": "Cheetah 工作区"},
        "permissions": ["intake:read", "intake:write", "rules:publish"],
        "csrf_token": digest("csrf:" + raw),
        "expires_at": aware(login.expires_at),
        "capabilities": {
            "modules": ["auth", "jobs", "intake", "outreach"],
            "mock_execution_allowed": settings.allow_mock,
            "model_configured": bool(
                settings.model_endpoint and settings.model_api_key and settings.model_name
            ),
            "search_configured": settings.search_provider != "disabled"
            or (
                settings.a03_web_backend == "pi_web_access"
                and settings.a03_plugin_provider in {"brave", "tavily", "exa", "deepseek"}
                and settings.a03_plugin_api_key is not None
            ),
            "voice_configured": False,
            "import_limits": {
                "max_items": settings.batch_limit,
                "max_file_bytes": settings.file_byte_limit,
                "max_text_chars": settings.text_char_limit,
            },
        },
    }


def throttle(db: Session, bucket: str, limit: int):
    from sqlalchemy.dialects.postgresql import insert as postgres_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    now = utcnow()
    bucket = digest(bucket + ":" + str(int(now.timestamp()) // 600))
    insert = postgres_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    # Count in a separate short transaction so failed authentication cannot roll it back.
    with Session(db.bind) as throttle_db, throttle_db.begin():
        throttle_db.execute(delete(LoginThrottle).where(LoginThrottle.expires_at < now))
        throttle_db.execute(
            insert(LoginThrottle)
            .values(bucket=bucket, attempts=0, expires_at=now + timedelta(minutes=10))
            .on_conflict_do_nothing()
        )
        count = throttle_db.scalar(
            update(LoginThrottle)
            .where(LoginThrottle.bucket == bucket)
            .values(attempts=LoginThrottle.attempts + 1)
            .returning(LoginThrottle.attempts)
        )
    if count > limit:
        raise DomainError("RATE_LIMITED", "操作过于频繁，请稍后再试", 429)


@router.post("/login", response_model=dto.Session)
def login(body: LoginInput, request: Request, response: Response, db: Db):
    check_origin(request)
    throttle(db, "login:" + body.username, request.app.state.settings.login_attempt_limit)
    user = db.scalar(select(Identity).where(Identity.username == body.username))
    # Perform the same expensive derivation for unknown users.
    stored = user.password_hash if user else "scrypt$unavailable$" + "0" * 128
    valid = verify_password(body.password, stored)
    if user is None or not user.enabled or not valid:
        raise DomainError("AUTH_REQUIRED", "用户名或密码不正确", 401)
    return create_session(request, response, db, user)


@router.post("/register", response_model=dto.Session, status_code=201)
def register(body: RegisterInput, request: Request, response: Response, db: Db):
    check_origin(request)
    if not request.app.state.settings.registration_enabled:
        raise DomainError("REGISTRATION_DISABLED", "当前暂未开放注册，请联系管理员", 403)
    # Trust the direct peer only, never a caller-supplied forwarding header.
    peer = request.client.host if request.client else "unknown"
    throttle(db, "register:" + peer, request.app.state.settings.registration_attempt_limit)
    user = Identity(
        username=body.username,
        display_name=body.display_name.strip(),
        organization_id=new_id(),
        password_hash=hash_password(body.password),
    )
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError as exc:
        raise DomainError("USERNAME_TAKEN", "该账号已被使用，请更换账号或登录", 409) from exc
    return create_session(request, response, db, user)


def create_session(request: Request, response: Response, db: Session, user: Identity):
    old = request.cookies.get(COOKIE)
    if old and (previous := db.get(LoginSession, digest(old))):
        db.delete(previous)
    raw = secrets.token_urlsafe(32)
    entry = LoginSession(
        token_hash=digest(raw),
        user_id=user.id,
        expires_at=utcnow() + timedelta(hours=request.app.state.settings.session_hours),
    )
    db.add(entry)
    db.flush()
    response.set_cookie(
        COOKIE,
        raw,
        httponly=True,
        samesite="lax",
        path="/",
        secure=request.app.state.settings.environment == "production",
        max_age=request.app.state.settings.session_hours * 3600,
    )
    return session_view(request, user, entry, raw)


@router.get("/me", response_model=dto.Session)
def me(request: Request, db: Db, user: User):
    raw = request.cookies[COOKIE]
    return session_view(request, user, db.get(LoginSession, digest(raw)), raw)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db, user: User):
    entry = db.get(LoginSession, digest(request.cookies[COOKIE]))
    db.delete(entry)
    response.delete_cookie(COOKIE, path="/")


def database_session(request: Request) -> Session:
    """Open an interview transaction using the platform database."""
    settings = request.app.state.settings
    if settings.database_url is None:
        raise DomainError("DEPENDENCY_NOT_READY", "尚未配置数据库", 503)
    return Session(get_engine(settings.database_url.get_secret_value()))


def require_identity(request: Request) -> dict:
    """Adapt the shared account; no separate development login or session table."""
    with database_session(request) as db:
        user = current_user(request, db)
        raw = request.cookies[COOKIE]
        login = db.get(LoginSession, digest(raw))
        return {
            "user_id": user.id,
            "organization_id": user.organization_id,
            "csrf_token": digest("csrf:" + raw),
            "expires_at": aware(login.expires_at).isoformat(),
        }
