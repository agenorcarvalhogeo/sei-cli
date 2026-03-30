from __future__ import annotations

from typing import Any

import httpx

from .contracts import OperationError


class OperationFailure(Exception):
    code = "operation_failed"
    retryable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_error(self) -> OperationError:
        return OperationError(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
        )


class AuthRequiredError(OperationFailure):
    code = "auth_required"


class SessionInvalidError(OperationFailure):
    code = "session_invalid"
    retryable = True


class UnitNotFoundError(OperationFailure):
    code = "unit_not_found"


class ProcessNotFoundError(OperationFailure):
    code = "process_not_found"


class DocumentNotFoundError(OperationFailure):
    code = "document_not_found"


class BlockNotFoundError(OperationFailure):
    code = "block_not_found"


class WorkflowViolationError(OperationFailure):
    code = "workflow_violation"


class ParseError(OperationFailure):
    code = "parse_error"


class UnsupportedStateError(OperationFailure):
    code = "unsupported_state"


def error_from_exception(exc: Exception) -> OperationError:
    if isinstance(exc, OperationFailure):
        return exc.to_error()

    if isinstance(exc, httpx.HTTPError):
        return OperationError(
            code="network_error",
            message=str(exc),
            retryable=True,
            details={},
        )

    return OperationError(
        code="parse_error",
        message=str(exc),
        retryable=False,
        details={},
    )
