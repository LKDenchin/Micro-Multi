"""Wall-clock autonomy budget shared by lead and workers."""

import json
import time
from dataclasses import dataclass, field
from typing import Any

from masp.compaction import build_deterministic_summary, wrap_compacted_summary


@dataclass
class WorkBudget:
    seconds: float = 28800
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


def compact_runtime_messages(
    messages: list[dict[str, Any]], max_chars: int, force: bool = False
) -> bool:
    if len(messages) < 16 or (
        not force and len(json.dumps(messages, ensure_ascii=False)) < max_chars
    ):
        return False
    # Keep the system and original task verbatim, and preserve complete recent tool exchanges.
    cut = max(2, len(messages) - 10)
    while cut > 2 and messages[cut].get("role") == "tool":
        cut -= 1
    head = messages[2:cut]
    if not head:
        return False
    summary = build_deterministic_summary(head)
    limit = max(2000, min(24000, max_chars // 3))
    if len(summary) > limit:
        half = limit // 2
        summary = (
            summary[:half]
            + "\n[Older checkpoint details condensed; full transcript is archived.]\n"
            + summary[-half:]
        )
    messages[2:cut] = [{"role": "user", "content": wrap_compacted_summary(summary)}]
    return True
