from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

from app.core.auth import router as auth_router
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.health import router as health_router
from app.core.openapi import install_openapi
from app.modules.intake.batches import router as batches_router
from app.modules.intake.corrections import router as corrections_router
from app.modules.intake.queries import router as queries_router
from app.modules.intake.router import router as intake_router
from app.modules.intake.workspace import router as workspace_router
from app.modules.outreach.router import router as outreach_router


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings if settings is not None else get_settings()
    application = FastAPI(
        title="Cheetah API",
        version="0.1.0",
        description="Intake workflow D01-D06. Live model/search/voice require separate validation.",
    )
    application.state.settings = runtime_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex
        try:
            response = await call_next(request)
        except Exception:
            # Server error middleware can otherwise re-raise and log sensitive exception values.
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "INTERNAL_ERROR",
                    "message": "请求失败，请提供请求标识供排查",
                    "request_id": request.state.request_id,
                    "details": None,
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(OperationalError)
    async def unavailable_database(request: Request, exc: OperationalError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": "DEPENDENCY_NOT_READY",
                "message": "数据库未就绪或暂时不可用",
                "request_id": request.state.request_id,
                "details": None,
            },
        )

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
                "details": exc.details,
            },
        )

    @application.exception_handler(Exception)
    async def unknown_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "请求失败，请提供请求标识供排查",
                "request_id": request.state.request_id,
                "details": None,
            },
            headers={"X-Request-ID": request.state.request_id, "Cache-Control": "no-store"},
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": f"HTTP_{exc.status_code}",
                "message": "Resource not found" if exc.status_code == 404 else "Request failed",
                "request_id": request.state.request_id,
                "details": None,
            },
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo request values, which may later include candidate data or credentials.
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "Invalid request",
                "request_id": request.state.request_id,
                "details": [
                    {"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()
                ],
            },
        )

    application.include_router(health_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(intake_router, prefix="/api/v1")
    application.include_router(batches_router, prefix="/api/v1")
    application.include_router(queries_router, prefix="/api/v1")
    application.include_router(corrections_router, prefix="/api/v1")
    application.include_router(workspace_router, prefix="/api/v1")
    application.include_router(outreach_router, prefix="/api/v1")
    install_openapi(application)
    return application


app = create_app()
