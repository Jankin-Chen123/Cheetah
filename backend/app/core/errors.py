from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, details: Any = None):
        self.code = code
        self.message = message
        self.status = status
        self.details = details
        super().__init__(code)


def not_found() -> DomainError:
    return DomainError("NOT_FOUND", "对象不存在或不可访问", 404)
