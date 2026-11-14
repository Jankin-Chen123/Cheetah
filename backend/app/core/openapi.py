from fastapi.openapi.utils import get_openapi

from app.modules.intake.schemas import ResumeBatchInput


def inline_schema(model):
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].split("/")[-1]])
            return {key: expand(item) for key, item in value.items()}
        return value

    return expand(schema)


def install_openapi(application):
    def build():
        if application.openapi_schema:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        schema["components"].setdefault("securitySchemes", {})["CookieAuth"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": "cheetah_session",
        }
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "patch", "put", "delete"}:
                    continue
                operation["x-implementation-status"] = "implemented-local"
                for code, response in operation["responses"].items():
                    if code == "202" or (code == "201" and path == "/api/v1/jobs"):
                        response.setdefault("headers", {})["Location"] = {
                            "description": "新岗位详情或持久化任务查询地址；幂等重放保持相同地址",
                            "schema": {"type": "string"},
                        }
                if path.startswith("/api/v1/health"):
                    continue
                if path != "/api/v1/auth/login":
                    operation["security"] = [{"CookieAuth": []}]
                params = operation.setdefault("parameters", [])
                for name in ["Origin"] if method != "get" else []:
                    params.append(
                        {
                            "name": name,
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    )
                if method != "get" and path != "/api/v1/auth/login":
                    params.append(
                        {
                            "name": "X-CSRF-Token",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    )
                if method == "post" and not path.startswith("/api/v1/auth/"):
                    params.append(
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": True,
                            "schema": {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{8,128}$"},
                        }
                    )
                for status in (401, 403, 404, 409, 413, 415, 422, 429, 500, 503):
                    operation["responses"][str(status)] = {
                        "description": "稳定错误码；不回显敏感输入或第三方异常",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
                        },
                    }
        schema["paths"]["/api/v1/jobs/{job_id}/resume-batches"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": inline_schema(ResumeBatchInput)},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["manifest", "files"],
                        "properties": {
                            "manifest": {
                                "type": "string",
                                "description": "JSON manifest with items and execution_mode",
                            },
                            "files": {
                                "type": "array",
                                "maxItems": 10,
                                "items": {"type": "string", "format": "binary"},
                            },
                        },
                    }
                },
            },
        }
        application.openapi_schema = schema
        return schema

    application.openapi = build
