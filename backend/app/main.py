from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.config import Settings, get_settings
from app.core.health import router as health_router
from app.modules.intake.router import router as intake_router
from app.modules.outreach.router import router as outreach_router


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings if settings is not None else get_settings()
    application = FastAPI(
        title="Cheetah API",
        version="0.1.0",
        description="Scaffold only. Business endpoints are not implemented.",
    )
    application.state.settings = runtime_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

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
    application.include_router(intake_router, prefix="/api/v1")
    application.include_router(outreach_router, prefix="/api/v1")
    return application


app = create_app()
