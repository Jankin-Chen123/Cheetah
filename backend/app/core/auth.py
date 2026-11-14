"""Minimal local account session boundary shared by business modules."""

import hashlib
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base, get_engine

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[str] = mapped_column(String(128))
    organization_id: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[int] = mapped_column(Integer)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


def database_session(request: Request):
    settings = request.app.state.settings
    if settings.database_url is None:
        raise HTTPException(503)
    return Session(get_engine(settings.database_url.get_secret_value()))


def check_origin(request: Request):
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise HTTPException(403)


def require_identity(request: Request) -> dict:
    token = request.cookies.get("cheetah_session", "")
    with database_session(request) as session:
        identity = session.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
        if identity is None or identity.expires_at <= time.time():
            raise HTTPException(401)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request)
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), identity.csrf):
                raise HTTPException(403)
        return {
            "user_id": identity.user_id,
            "organization_id": identity.organization_id,
            "csrf_token": identity.csrf,
            "expires_at": identity.expires_at,
        }


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response):
    check_origin(request)
    settings = request.app.state.settings
    if settings.environment != "development" or settings.local_password is None:
        raise HTTPException(503)
    if not (
        secrets.compare_digest(data.username, settings.local_username)
        and secrets.compare_digest(data.password, settings.local_password.get_secret_value())
    ):
        raise HTTPException(401)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with database_session(request) as session, session.begin():
        session.add(
            LoginSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                csrf=csrf,
                user_id="local-reviewer",
                organization_id="local-development",
                expires_at=int(time.time()) + 43200,
            )
        )
    response.set_cookie("cheetah_session", token, httponly=True, samesite="lax", max_age=43200)
    response.headers["Cache-Control"] = "no-store"
    return {"user": {"id": "local-reviewer"}, "csrf_token": csrf}


@router.get("/me")
def me(request: Request):
    return require_identity(request)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    require_identity(request)
    with database_session(request) as session, session.begin():
        token = request.cookies.get("cheetah_session", "")
        identity = session.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
        if identity:
            session.delete(identity)
    response.delete_cookie("cheetah_session")
