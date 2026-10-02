"""Shared model termination recovery and upstream execution-evidence integration."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlparse

from masp._vendor.deerflow.messages import AIMessage, ToolMessage
from masp._vendor.deerflow.model_length_termination_detectors import default_detectors
from masp._vendor.deerflow.receipt_verification import verify_receipt_citations
from masp._vendor.deerflow.tool_receipt import (
    ToolReceipt,
    make_tool_receipt,
    receipt_id,
    render_tool_receipts_with_snapshot,
)


class VisibleOutputFilter:
    """Suppress internal memory across arbitrary SSE fragment boundaries."""

    opening = "<tool-execution-memory>"
    closing = "</tool-execution-memory>"

    def __init__(self) -> None:
        self.buffer = ""
        self.hidden = False

    def push(self, text: str, *, final: bool = False) -> str:
        self.buffer += text
        visible = ""
        while self.buffer:
            tag = self.closing if self.hidden else self.opening
            offset = self.buffer.find(tag)
            if offset >= 0:
                if not self.hidden:
                    visible += self.buffer[:offset]
                self.buffer = self.buffer[offset + len(tag) :]
                self.hidden = not self.hidden
                continue
            retained = 0
            if not final:
                for length in range(1, min(len(tag), len(self.buffer) + 1)):
                    if self.buffer.endswith(tag[:length]):
                        retained = length
            consumed = len(self.buffer) - retained
            if not self.hidden:
                visible += self.buffer[:consumed]
            self.buffer = self.buffer[consumed:]
            break
        return visible


@dataclass
class ModelRecovery:
    """Bounded retries: preserve tools, never execute length-truncated arguments."""

    limit: int = 2
    attempts: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)

    def reason(
        self,
        *,
        content: str,
        calls: Any,
        finish_reason: str | None,
        reasoning: str = "",
        interrupted: bool = False,
    ) -> str | None:
        message = AIMessage(
            content=content,
            response_metadata={"finish_reason": finish_reason},
            tool_calls=list(calls.values()) if isinstance(calls, dict) else calls,
        )
        if any(detector.detect(message) for detector in default_detectors()):
            return "model_length_capped"
        if interrupted:
            return "stream_interrupted"
        if not content.strip() and not calls:
            return "reasoning_only" if reasoning else "empty_response"
        return None

    def success(self) -> None:
        """Retry limits apply to consecutive failures, not the entire engineering run."""
        self.attempts = 0

    def continuation(self, reason: str) -> dict[str, str] | None:
        self.records.append({"reason": reason, "attempt": self.attempts + 1})
        if self.attempts >= self.limit:
            return None
        self.attempts += 1
        return {
            "role": "user",
            "content": (
                f"执行系统检测到上一响应未完成（{reason}），正在自动恢复。"
                "保留原始用户目标和已完成工作，直接推进下一项实际操作。"
                "不要重复长篇设计，不要把子代理当作模拟对象；只有真实工具返回才是执行证据。"
                "如果任务需要写文件或调度成员，请立即发出完整的标准工具调用；"
                "单次文件写入内容控制在 2000 字符以内，大文件先 write_file 写第一段，之后用 append=true 追加。"
                "若上一段是普通回答，只续写缺失部分，不要从头重复。若是问答，请直接给出完整答案。"
            ),
        }


def response_deadline(config: Any) -> float:
    """Idle timeout is configured separately; allow slow, continuously active generation."""
    idle = float(getattr(config, "timeout_seconds", 90))
    tokens = int(getattr(config, "max_output_tokens", 8192) or 8192)
    return min(1800.0, max(300.0, idle * 3, tokens / 10 + 120))


async def model_stream_lines(
    response: Any,
    idle_seconds: float,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
    heartbeat_seconds: float = 5.0,
) -> AsyncIterator[str]:
    """Keepalives are transport activity, not model progress. Own exactly one read."""
    iterator = response.aiter_lines().__aiter__()
    last_activity = time.monotonic()
    last_heartbeat = last_activity
    pending: asyncio.Task[Any] | None = None
    try:
        while True:
            remaining = idle_seconds - (time.monotonic() - last_activity)
            if remaining <= 0:
                raise TimeoutError("模型在空闲时限内没有返回有效内容")
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=min(heartbeat_seconds, remaining))
            if heartbeat and time.monotonic() - last_heartbeat >= heartbeat_seconds:
                await heartbeat()
                last_heartbeat = time.monotonic()
            if not done:
                continue
            try:
                line = pending.result()
            except StopAsyncIteration:
                break
            finally:
                pending = None
            if line.startswith("data:"):
                raw = line[5:].strip()
                if raw == "[DONE]":
                    last_activity = time.monotonic()
                else:
                    try:
                        choices = json.loads(raw).get("choices") or []
                        if any(
                            c.get("finish_reason")
                            or any(
                                (c.get("delta") or {}).get(key)
                                for key in ("content", "reasoning_content", "tool_calls")
                            )
                            for c in choices
                        ):
                            last_activity = time.monotonic()
                    except (ValueError, AttributeError, TypeError):
                        pass
            yield line
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        close = getattr(iterator, "aclose", None)
        if close:
            await close()


def preserve_partial_response(
    messages: list[dict[str, Any]], content: str, reasoning: str, calls: Any
) -> None:
    # Never replay truncated action arguments. Keep text to let continuation advance.
    if content.strip() and not calls and "DSML" not in content:
        messages.append({"role": "assistant", "content": content, "reasoning_content": reasoning})


def stamp_receipt(
    position: int, name: str, arguments: str, output: str, call_id: str, failed: bool
) -> ToolReceipt:
    try:
        parsed = json.loads(arguments)
    except ValueError:
        parsed = {}
    receipt = make_tool_receipt(
        {"id": call_id, "name": name, "args": parsed},
        ToolMessage(content=output, status="error" if failed else "success"),
    )
    return cast(ToolReceipt, {"id": receipt_id(position), **receipt})


def evidence_context(receipts: list[ToolReceipt]) -> tuple[str, list[ToolReceipt]]:
    return render_tool_receipts_with_snapshot(receipts, max_chars=5000)


def evaluate_report(report: str, receipts: list[ToolReceipt]) -> dict[str, Any]:
    return dict(verify_receipt_citations(report, receipts))


def configure_provider(payload: dict[str, Any], base_url: str, *, recovering: bool) -> None:
    """Official DeepSeek parameters, scoped to the supported provider/model pair."""
    if urlparse(base_url).hostname == "api.deepseek.com" and payload["model"] in {
        "deepseek-flash",
        "deepseek-v4-pro",
    }:
        payload["thinking"] = {"type": "disabled" if recovering else "enabled"}
        payload["reasoning_effort"] = "none" if recovering else "low"
        # Every assistant frame in a thinking tool cycle must carry its reasoning.
        for message in payload["messages"]:
            if message.get("role") == "assistant":
                message.setdefault("reasoning_content", "")


def requests_execution(text: str) -> bool:
    """Only guards false delivery; does not select roles, paths, or a task graph."""
    if re.match(r"\s*(什么|为什么|怎么|如何|解释|介绍|请问|what\b|why\b|how\b)", text, re.I):
        return False
    return bool(
        re.search(
            r"制作|做一个|创建|实现|编写|开发|修复|重构|重写|修改|删除|"
            r"\b(build|implement|create|fix|rewrite|refactor|delete)\b",
            text,
            re.I,
        )
    )


def merge_stream_identifier(current: str, fragment: str) -> str:
    """Accept both fragmented and repeated cumulative tool identifiers."""
    if not fragment or fragment == current:
        return current
    if fragment.startswith(current):
        return fragment
    return current + fragment
