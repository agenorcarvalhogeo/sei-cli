from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "1"


@dataclass(slots=True)
class OperationError:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NextAction:
    action: str
    label: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperationResult:
    schema_version: str = SCHEMA_VERSION
    ok: bool = True
    operation: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    resolved_ids: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    next_actions: list[NextAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: OperationError | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
