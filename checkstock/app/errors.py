# -*- coding: utf-8 -*-
from typing import Any, Optional


class DomainError(Exception):
    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str, *, code: Optional[str] = None, **context: Any) -> None:
        super().__init__(message)
        self.message: str = message
        if code is not None:
            self.code = code
        self.context: dict[str, Any] = context

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.context}


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class InvalidState(Conflict):
    code = "invalid_state"


class InsufficientStock(Conflict):
    code = "insufficient_stock"
