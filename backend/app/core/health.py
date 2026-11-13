from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "cheeta-api", "stage": "initialization"}


@router.get("/ready")
def readiness(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    database_ready = False
    if settings.database_url is not None:
        try:
            database_ready = database.check_database(settings)
        except Exception:
            # Connection exceptions may contain secrets; never return their raw text.
            database_ready = False
    return JSONResponse(
        status_code=200 if database_ready else 503,
        content={
            "status": "ready" if database_ready else "not_ready",
            "checks": {"database": "ok" if database_ready else "unavailable"},
            "stage": "initialization",
        },
    )
