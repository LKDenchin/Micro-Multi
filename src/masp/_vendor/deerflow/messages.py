"""Transport compatibility types for the vendored pure DeerFlow algorithms."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIMessage:
    content: Any = ""
    response_metadata: dict[str, Any] = field(default_factory=dict)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    invalid_tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolMessage:
    content: Any = ""
    status: str = "success"
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
