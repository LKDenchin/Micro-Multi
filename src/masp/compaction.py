from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

CHECKPOINT_PREAMBLE = (
    "Earlier messages in this conversation have been compacted into the "
    "following summary to save context space. Use it as your ground-truth "
    "record of what happened before, then continue naturally from the "
    "recent messages that follow.\n\n"
)

COMPACTION_INSTRUCTION = """You are a context compaction engine for a coding agent. Produce a dense, structured checkpoint of the conversation above so the agent can seamlessly resume work after older messages are discarded.

Write ONLY the summary — no preamble, no meta-commentary. Use the sections below; omit any section that has nothing relevant.

## Task & Intent
- The user's original request and any refined goals or constraints discovered during the session.

## Completed Work
- Concrete actions taken and their outcomes. Reference exact file paths, function/class names, and CLI commands executed.

## Current State
- What is currently in progress or partially done.
- Files created, modified, or deleted and their current status (working, broken, untested).

## Key Findings & Context
- Important code patterns, architectural decisions, API contracts, error messages, or root causes discovered.
- Non-obvious constraints, edge cases, or environment details the agent must remember.

## Errors & Dead Ends
- Approaches that failed and why, so the agent does not repeat them.

## Remaining Work & Next Steps
- Specific items still to be done, in priority order.

Rules:
- Preserve exact identifiers: file paths, symbol names, branch names, URLs, config keys, error codes.
- Be concise — use bullet fragments, not prose. Every token must earn its place.
- Do NOT include full file contents or long command outputs; summarize what they showed."""

GENTLE_REMINDER = (
    "[System Notice] You have called the same tool with identical arguments multiple times. "
    "If you are waiting for an async result, consider whether the approach needs adjustment."
)


def detailed_repeat_reminder(tool_name: str, count: int) -> str:
    return (
        f'[System Warning] Tool "{tool_name}" has been called {count} times with identical arguments. '
        "This strongly suggests a loop. Please stop and reconsider your approach:\n"
        "1. Is the tool returning the expected result?\n"
        "2. Are you polling for something that will never change?\n"
        "3. Should you try a different strategy or report the issue to the user?"
    )


def wrap_compacted_summary(summary_body: str) -> str:
    clean = str(summary_body or "").strip()
    if "<compacted-summary>" in clean:
        return clean
    return f"{CHECKPOINT_PREAMBLE}<compacted-summary>\n{clean}\n</compacted-summary>"


def extract_compacted_summary(text: str) -> str | None:
    match = re.search(r"<compacted-summary>\s*([\s\S]*?)\s*</compacted-summary>", str(text or ""))
    if not match:
        return None
    return match.group(1).strip()


@dataclass
class ToolResultPruner:
    """Ports @deepseek-harness/compaction-tool-result-pruner."""

    threshold_chars: int = 2000
    head_chars: int = 500
    tail_chars: int = 300
    max_chars: int | None = None

    def __post_init__(self) -> None:
        if self.max_chars is not None:
            self.threshold_chars = int(self.max_chars)
            self.head_chars = max(40, int(self.max_chars * 0.5))
            self.tail_chars = max(20, int(self.max_chars * 0.25))

    def prune(self, tool_name_or_text: str, text: str | None = None) -> str:
        target = tool_name_or_text if text is None else text
        pruned, _ = self.prune_text(target)
        return pruned

    def prune_text(self, text: str) -> tuple[str, int]:
        raw = str(text or "")
        if len(raw) <= self.threshold_chars:
            return raw, 0
        head = raw[: self.head_chars]
        tail = raw[-self.tail_chars :] if self.tail_chars > 0 else ""
        omitted = max(0, len(raw) - self.head_chars - self.tail_chars)
        pruned = f"{head}\n\n... [{omitted} chars pruned] ...\n\n{tail}"
        saved = max(0, len(raw) - len(pruned))
        return pruned, saved

    def prune_tool_trace(self, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pruned_list: list[dict[str, Any]] = []
        for item in trace or []:
            if not isinstance(item, dict):
                continue
            copy_item = dict(item)
            for key in ("detail", "output", "stdout", "stderr", "content"):
                if isinstance(copy_item.get(key), str):
                    pruned_val, _ = self.prune_text(copy_item[key])
                    copy_item[key] = pruned_val
            pruned_list.append(copy_item)
        return pruned_list


@dataclass
class RepeatToolReminder:
    """Ports @deepseek-harness/repeat-tool-reminder."""

    thresholds: tuple[int, ...] = (3, 5, 8)
    threshold: int | None = None
    last_key: str = ""
    repeat_count: int = 0

    def __post_init__(self) -> None:
        if self.threshold is not None:
            t = int(self.threshold)
            self.thresholds = (t, t + 2, t + 5)

    @staticmethod
    def _stable_args(args: Any) -> str:
        if isinstance(args, dict):
            try:
                return json.dumps(args, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(args)
        return str(args or "")

    def record(self, tool_name: str, args: Any) -> str | None:
        key = f"{tool_name}:{self._stable_args(args)}"
        if key == self.last_key:
            self.repeat_count += 1
        else:
            self.last_key = key
            self.repeat_count = 1

        if self.repeat_count not in self.thresholds:
            return None
        first_threshold = self.thresholds[0] if self.thresholds else 3
        if self.repeat_count == first_threshold:
            return f"{GENTLE_REMINDER} (tool: {tool_name})"
        return detailed_repeat_reminder(tool_name, self.repeat_count)


def _extract_tool_items(msg: dict[str, Any]) -> list[dict[str, Any]]:
    raw_meta = msg.get("meta")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    raw_trace = meta.get("tool_trace")
    trace = raw_trace if isinstance(raw_trace, list) else []
    raw_events = msg.get("tool_events")
    events = raw_events if isinstance(raw_events, list) else []
    return [*trace, *events]


def format_message_with_tool_memory(
    msg_or_content: dict[str, Any] | str,
    pruner_or_events: ToolResultPruner | list[dict[str, Any]] | None = None,
) -> Any:
    """Ensure assistant messages retain a compact summary of tool calls so multi-turn memory is preserved."""
    if isinstance(msg_or_content, str):
        events = pruner_or_events if isinstance(pruner_or_events, list) else []
        formatted_dict = format_message_with_tool_memory(
            {"role": "assistant", "content": msg_or_content, "tool_events": events},
            None,
        )
        return (formatted_dict.get("_tool_memory", "") + "\n\n" + formatted_dict["content"]).strip()
    msg = msg_or_content
    pruner = pruner_or_events if isinstance(pruner_or_events, ToolResultPruner) else None
    role = str(msg.get("role") or "user")
    content = str(msg.get("content") or "")
    if role == "assistant":
        content = re.sub(
            r"<tool-execution-memory>[\s\S]*?(?:</tool-execution-memory>|$)",
            "",
            content,
            flags=re.I,
        )
    for attachment in msg.get("attachments") or []:
        if isinstance(attachment, dict):
            content += (
                "\n\n[用户附加文件："
                + str(attachment.get("name", "attachment.txt"))[:200]
                + "]\n"
                + str(attachment.get("content", ""))[:250_000]
                + (
                    "\n[File path: " + attachment["workspace_path"] + "]"
                    if attachment.get("workspace_path")
                    else ""
                )
            )
    tool_trace = _extract_tool_items(msg)

    if role == "assistant" and tool_trace:
        active_pruner = pruner or ToolResultPruner(
            threshold_chars=900, head_chars=360, tail_chars=180
        )
        trace_lines: list[str] = []
        for entry in tool_trace[:8]:
            if not isinstance(entry, dict):
                continue
            t_name = str(entry.get("name") or entry.get("tool") or "tool")
            t_title = str(
                entry.get("title")
                or entry.get("label")
                or entry.get("path")
                or entry.get("command")
                or ""
            )
            t_status = str(entry.get("status") or "ok")
            t_detail = str(entry.get("detail") or entry.get("output") or entry.get("diff") or "")
            t_detail_pruned, _ = active_pruner.prune_text(t_detail)
            header = f"- [{t_name}] {t_title} ({t_status})".strip()
            if t_detail_pruned:
                trace_lines.append(f"{header}: {t_detail_pruned}")
            else:
                trace_lines.append(header)
        if trace_lines:
            tool_block = (
                "<tool-execution-memory>\n" + "\n".join(trace_lines) + "\n</tool-execution-memory>"
            )
            return {"role": role, "content": content, "_tool_memory": tool_block}
    return {"role": role, "content": content}


def model_history(messages: list[dict[str, Any]], pruner: ToolResultPruner) -> list[dict[str, Any]]:
    """Execution traces are reference data, never previous assistant speech."""
    result = []
    for message in messages:
        formatted = format_message_with_tool_memory(message, pruner)
        memory = formatted.pop("_tool_memory", None)
        if memory:
            result.append(
                {
                    "role": "user",
                    "content": "Execution reference data. Do not reproduce this internal record in your reply:\n"
                    + memory,
                }
            )
        result.append(formatted)
    return result


def build_deterministic_summary(messages: list[dict[str, Any]], previous_summary: str = "") -> str:
    """Fallback deterministic structured summary following DeepSeek-Harness 6-section schema."""
    user_intents: list[str] = []
    user_constraints: list[str] = []
    completed_work: list[str] = []
    current_state: list[str] = []
    key_findings: list[str] = []
    errors: list[str] = []

    pruner = ToolResultPruner(threshold_chars=320, head_chars=180, tail_chars=80)

    for msg in messages:
        role = str(msg.get("role") or "")
        text = str(msg.get("content") or "").strip()
        trace = _extract_tool_items(msg)

        if role == "user" and text:
            existing = extract_compacted_summary(text)
            if existing and not previous_summary:
                previous_summary = existing
                continue
            intent_pruner = (
                ToolResultPruner(threshold_chars=4000, head_chars=2800, tail_chars=1000)
                if not user_intents
                else pruner
            )
            snippet, _ = intent_pruner.prune_text(text.replace("\n", " "))
            user_intents.append(f"- {snippet}")
            for line in text.splitlines():
                if re.search(
                    r"必须|禁止|不得|保留|要求|验收|must|never|required|constraint", line, re.I
                ):
                    constraint, _ = pruner.prune_text(line)
                    user_constraints.append(f"- {constraint}")
        elif role == "tool":
            snippet, _ = pruner.prune_text(text.replace("\n", " "))
            completed_work.append(f"- Tool result {msg.get('tool_call_id', '')}: {snippet}")
        elif role == "assistant":
            for item in trace:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "tool")
                title = str(item.get("title") or item.get("label") or item.get("path") or "")
                status = str(item.get("status") or "ok")
                detail, _ = pruner.prune_text(
                    str(item.get("detail") or item.get("output") or item.get("diff") or "").replace(
                        "\n", " "
                    )
                )
                if status in {"error", "failed", "blocked"}:
                    errors.append(f"- `{name}` ({title}): {detail}")
                else:
                    completed_work.append(f"- `{name}` {title}: {detail}".rstrip(": "))
            if text:
                snippet, _ = pruner.prune_text(text.replace("\n", " "))
                current_state.append(f"- Assistant response: {snippet}")

    sections: list[str] = []
    if previous_summary:
        prior, _ = ToolResultPruner(
            threshold_chars=12000, head_chars=6000, tail_chars=5000
        ).prune_text(previous_summary.strip())
        sections.append(f"## Prior Checkpoint\n{prior}")
    if user_intents:
        sections.append(
            "## Task & Intent\n" + "\n".join(dict.fromkeys(user_intents[:1] + user_intents[-6:]))
        )
    if user_constraints:
        sections.append(
            "## User Constraints\n"
            + "\n".join(dict.fromkeys(user_constraints[:12] + user_constraints[-12:]))
        )
    if completed_work:
        sections.append("## Completed Work\n" + "\n".join(completed_work[-10:]))
    if current_state:
        sections.append("## Current State\n" + "\n".join(current_state[-5:]))
    if key_findings:
        sections.append("## Key Findings & Context\n" + "\n".join(key_findings[-5:]))
    if errors:
        sections.append("## Errors & Dead Ends\n" + "\n".join(errors[-5:]))
    sections.append(
        "## Remaining Work & Next Steps\n- Continue addressing the latest user messages using the preserved context above."
    )

    return "\n\n".join(sections).strip()


COMPACTABLE_TOOLS = {
    "read_file",
    "read_workspace_file",
    "list_files",
    "list_workspace_files",
    "glob",
    "glob_workspace_files",
    "grep",
    "search_files",
    "search_workspace_code",
    "run_command",
    "run_workspace_command",
    "web_search",
    "web_fetch",
    "edit_file",
    "write_file",
}

MICRO_COMPACT_CLEARED_MARKER = "[Old tool result content cleared]"


def compute_effective_context_window(
    max_context_tokens: int = 64000,
    max_output_tokens: int = 8192,
) -> dict[str, int]:
    """Layer 1 (Claude Code): Reserve output space and compute multi-stage warning/auto-compact thresholds."""
    total = max(4000, int(max_context_tokens or 64000))
    reserved_output = min(int(max_output_tokens or 8192), max(1000, int(total * 0.15)), 20000)
    effective_window = max(2000, total - reserved_output)
    return {
        "max_context_tokens": total,
        "reserved_output_tokens": reserved_output,
        "effective_window": effective_window,
        "warning_threshold": int(effective_window * 0.80),
        "error_threshold": int(effective_window * 0.85),
        "auto_compact_threshold": int(effective_window * 0.90),
        "blocking_limit": int(effective_window * 0.97),
    }


def _parse_iso_minutes_gap(older_iso: str, newer_iso: str) -> float:
    from datetime import datetime

    if not older_iso or not newer_iso:
        return 0.0
    try:
        t1 = datetime.fromisoformat(str(older_iso).replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(str(newer_iso).replace("Z", "+00:00"))
        return max(0.0, (t2 - t1).total_seconds() / 60.0)
    except Exception:
        return 0.0


def micro_compact_messages(
    messages: list[dict[str, Any]],
    *,
    keep_recent_tool_messages: int = 4,
    time_gap_minutes: float = 60.0,
) -> tuple[list[dict[str, Any]], int]:
    """Layers 3 & 4 (Claude Code): Path-based and Time-based Micro-Compaction.
    Clears bulky older tool results while preserving tool names, paths, and recent turns."""
    if not messages:
        return [], 0

    # Layer 4: Check time gap between last two turns; if cache expired (>60m), keep fewer bulky tool results
    effective_keep = keep_recent_tool_messages
    if len(messages) >= 2:
        gap = _parse_iso_minutes_gap(
            str(messages[-2].get("created_at") or ""),
            str(messages[-1].get("created_at") or ""),
        )
        if gap >= time_gap_minutes:
            effective_keep = min(effective_keep, 2)

    assistant_with_tools_indices = [
        idx
        for idx, msg in enumerate(messages)
        if msg.get("role") == "assistant" and _extract_tool_items(msg)
    ]
    protected_indices = (
        set(assistant_with_tools_indices[-effective_keep:]) if effective_keep > 0 else set()
    )

    chars_saved = 0
    result: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if idx in protected_indices or msg.get("role") != "assistant":
            result.append(dict(msg))
            continue
        copy_msg = dict(msg)
        raw_events = copy_msg.get("tool_events")
        if isinstance(raw_events, list) and raw_events:
            new_events = []
            for ev in raw_events:
                if not isinstance(ev, dict):
                    continue
                ev_copy = dict(ev)
                t_name = str(ev_copy.get("short_name") or ev_copy.get("name") or "").lower()
                if not t_name or t_name in COMPACTABLE_TOOLS:
                    for field_key in ("output", "diff", "detail"):
                        val = str(ev_copy.get(field_key) or "")
                        if len(val) > 280:
                            chars_saved += len(val) - len(MICRO_COMPACT_CLEARED_MARKER)
                            ev_copy[field_key] = MICRO_COMPACT_CLEARED_MARKER
                new_events.append(ev_copy)
            copy_msg["tool_events"] = new_events
        result.append(copy_msg)
    return result, max(0, chars_saved)


def build_session_memory_summary(
    messages: list[dict[str, Any]],
    previous_summary: str = "",
) -> str:
    """Layer 2 Priority 1 (Claude Code SM Compact): Zero-LLM-cost Session Memory synthesis.
    Extracts structured touched files, symbols, architecture notes, and task progress."""
    touched_files: dict[str, str] = {}
    symbols_mentioned: list[str] = []
    for msg in messages:
        content = str(msg.get("content") or "")
        for match in re.findall(
            r"`([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+|[A-Za-z_][A-Za-z0-9_]*\(\))`", content
        ):
            if "." in match and "/" in match.replace("\\", "/"):
                clean_p = match.replace("\\", "/")
                touched_files.setdefault(clean_p, "referenced")
            elif match.endswith("()") and match not in symbols_mentioned:
                symbols_mentioned.append(match)
        for ev in _extract_tool_items(msg):
            if not isinstance(ev, dict):
                continue
            path = str(ev.get("path") or "").strip().replace("\\", "/")
            cat = str(ev.get("category") or ev.get("name") or "")
            if path:
                added = int(ev.get("added", 0) or 0)
                removed = int(ev.get("removed", 0) or 0)
                if added or removed:
                    touched_files[path] = f"modified (+{added} -{removed})"
                elif "edit" in cat or "write" in cat:
                    touched_files[path] = "modified"
                else:
                    touched_files.setdefault(path, "read")

    base_summary = build_deterministic_summary(messages, previous_summary=previous_summary)
    extra_sections: list[str] = []
    if touched_files:
        file_lines = [f"- `{path}` ({status})" for path, status in list(touched_files.items())[:15]]
        extra_sections.append("## Session Memory: Touched Files\n" + "\n".join(file_lines))
    if symbols_mentioned:
        extra_sections.append(
            "## Session Memory: Key Symbols\n- "
            + ", ".join(f"`{s}`" for s in symbols_mentioned[:16])
        )
    if extra_sections:
        return base_summary + "\n\n" + "\n\n".join(extra_sections)
    return base_summary


def estimate_context_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        total += len(str(msg.get("content") or ""))
        for item in _extract_tool_items(msg):
            if isinstance(item, dict):
                total += len(
                    str(item.get("detail") or item.get("output") or item.get("diff") or "")
                )
    return total


@dataclass
class CompactionResult:
    compacted: bool
    summary: str
    messages_for_llm: list[dict[str, str]]
    compacted_messages_for_storage: list[dict[str, Any]]
    original_count: int
    retained_count: int
    chars_before: int
    chars_after: int
    layer_used: str = "none"
    micro_chars_saved: int = 0

    @property
    def checkpoint_content(self) -> str:
        if self.compacted and self.messages_for_llm:
            return str(self.messages_for_llm[0].get("content") or "")
        return wrap_compacted_summary(self.summary) if self.summary else ""

    @property
    def kept_count(self) -> int:
        return max(0, self.retained_count - 1) if self.compacted else self.retained_count

    def __getitem__(self, key: str) -> Any:
        if key == "checkpoint_content":
            return self.checkpoint_content
        if key == "kept_count":
            return self.kept_count
        return getattr(self, key)


def compact_conversation_messages(
    messages: list[dict[str, Any]],
    *,
    force: bool = False,
    max_context_chars: int = 24000,
    max_message_count: int = 18,
    keep_recent: int = 6,
    max_context_tokens: int | None = None,
    llm_summarizer: Callable[[str], str | None] | None = None,
) -> CompactionResult:
    """5-Layer Claude Code Context Compression Pipeline:
    L1 Effective Window -> L3/L4 Micro-Compaction -> L2 SM Compact / Legacy Compact -> L5 Post-Compact Cleanup."""
    if max_context_tokens is not None and max_context_chars == 24000:
        win = compute_effective_context_window(max_context_tokens)
        max_context_chars = max(6000, int(win["auto_compact_threshold"] * 2.5))
    pruner = ToolResultPruner()
    chars_before = estimate_context_chars(messages)
    original_count = len(messages)

    # Layer 3 & 4: Always apply Micro-Compaction to old bulky tool outputs first
    micro_messages, micro_saved = micro_compact_messages(
        messages, keep_recent_tool_messages=max(2, min(6, keep_recent))
    )
    formatted_all = model_history(micro_messages, pruner)
    chars_after_micro = estimate_context_chars(micro_messages)

    existing_summary = ""
    if messages:
        first_extracted = extract_compacted_summary(str(messages[0].get("content") or ""))
        if first_extracted:
            existing_summary = first_extracted

    should_compact = (
        force
        or original_count > max_message_count
        or chars_after_micro > max_context_chars
        or (keep_recent != 6 and original_count > keep_recent)
    )
    if not should_compact or original_count <= 2:
        chars_after = sum(len(m.get("content") or "") for m in formatted_all)
        return CompactionResult(
            compacted=False,
            summary=existing_summary,
            messages_for_llm=formatted_all,
            compacted_messages_for_storage=list(micro_messages),
            original_count=original_count,
            retained_count=original_count,
            chars_before=chars_before,
            chars_after=chars_after,
            layer_used="micro_compact" if micro_saved > 0 else "none",
            micro_chars_saved=micro_saved,
        )

    actual_keep = min(keep_recent, max(2, original_count - 1))
    if force and original_count <= keep_recent:
        actual_keep = max(2, original_count // 2)

    head_messages = micro_messages[:-actual_keep]
    tail_messages = micro_messages[-actual_keep:]

    summary_body = ""
    layer_used = "sm_compact"
    if llm_summarizer is not None and head_messages:
        transcript_lines: list[str] = []
        for m in head_messages:
            fm = format_message_with_tool_memory(m, pruner)
            transcript_lines.append(
                f"[{fm['role'].upper()}]\n{fm['content']}\n{fm.get('_tool_memory', '')}"
            )
        prompt_text = "\n\n".join(transcript_lines) + "\n\n---\n\n" + COMPACTION_INSTRUCTION
        try:
            llm_out = llm_summarizer(prompt_text)
            if llm_out and str(llm_out).strip():
                summary_body = str(llm_out).strip()
                layer_used = "llm_compact"
        except Exception:
            summary_body = ""

    if not summary_body:
        summary_body = build_session_memory_summary(
            head_messages, previous_summary=existing_summary
        )

    # Layer 5: Post-Compact Cleanup — build clean checkpoint and reset stale tool traces on compacted head
    wrapped = wrap_compacted_summary(summary_body)
    checkpoint_storage_msg: dict[str, Any] = {
        "id": "msg-compacted-checkpoint",
        "role": "user",
        "content": wrapped,
        "created_at": tail_messages[0].get("created_at", "") if tail_messages else "",
        "meta": {
            "compacted": True,
            "layer_used": layer_used,
            "compacted_count": len(head_messages),
            "chars_before": chars_before,
            "micro_chars_saved": micro_saved,
        },
    }

    new_storage = [checkpoint_storage_msg] + list(tail_messages)
    new_llm_messages = [{"role": "user", "content": wrapped}] + model_history(tail_messages, pruner)
    chars_after = sum(len(m.get("content") or "") for m in new_llm_messages)

    return CompactionResult(
        compacted=True,
        summary=summary_body,
        messages_for_llm=new_llm_messages,
        compacted_messages_for_storage=new_storage,
        original_count=original_count,
        retained_count=len(new_storage),
        chars_before=chars_before,
        chars_after=chars_after,
        layer_used=layer_used,
        micro_chars_saved=micro_saved,
    )


# =========================================================================
# Microsoft ACON: Agent Context Optimization
# Reference: https://github.com/microsoft/acon
# =========================================================================


class ObservationOptimizer:
    """ACON Observation Optimizer (ctxopt.obs_optimizer).

    Optimizes tool execution observations to reduce token bloat while
    preserving key task-relevant state changes, errors, stack traces, and test verdicts.
    """

    def __init__(
        self, threshold_chars: int = 1800, max_chars: int = 2400, max_lines: int | None = None
    ) -> None:
        self.threshold_chars = threshold_chars
        self.max_chars = max_chars
        self.max_lines = max_lines

    def check_summarization_needed(self, observation: str, threshold: int | None = None) -> bool:
        th = self.threshold_chars if threshold is None else threshold
        return len(str(observation or "")) > th

    def optimize(self, command: str, log: str) -> str:
        res = self.optimize_observation(f"run: {command}", "pytest", log)
        if self.max_lines and isinstance(res, str):
            lines = res.splitlines()
            if len(lines) > self.max_lines:
                half = self.max_lines // 2
                res = "\n".join(lines[:half] + ["... [ACON compressed] ..."] + lines[-half:])
        return res

    def optimize_observation(
        self,
        task: str,
        tool_name: str,
        observation: str,
        max_chars: int | None = None,
    ) -> str:
        raw = str(observation or "").strip()
        limit = self.max_chars if max_chars is None else max_chars
        if len(raw) <= self.threshold_chars:
            return raw

        # Rule 1: Python/Node/Pytest test logs: preserve summary line, failures, errors
        if "test" in tool_name or "pytest" in raw.lower() or "passed" in raw.lower():
            lines = raw.splitlines()
            summary_lines = [
                line
                for line in lines
                if any(
                    k in line.lower()
                    for k in ("passed", "failed", "error", "skipped", "failure", "assert")
                )
            ]
            error_block = []
            capture_error = False
            for line in lines:
                if any(
                    err_tag in line
                    for err_tag in (
                        "FAIL",
                        "ERROR",
                        "Traceback",
                        "AssertionError",
                        "SyntaxError",
                        "TypeError",
                        "ValueError",
                    )
                ):
                    capture_error = True
                if capture_error:
                    error_block.append(line)
                    if len(error_block) >= 30:
                        break
            preserved = "\n".join(summary_lines[:8])
            if error_block:
                preserved += "\n\n[ACON Test Error Extraction]\n" + "\n".join(error_block[:25])
            if len(preserved) > limit:
                return preserved[:limit] + "\n... [ACON observation compressed]"
            return f"[ACON Optimized Test Run]\n{preserved}"

        # Rule 2: Shell/CLI command execution output: preserve exit code, head/tail & errors
        if tool_name in {"run_command", "bash", "execute_command"} or '"exit_code"' in raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "stdout" in data and "stderr" in data:
                    code = data.get("exit_code", 0)
                    out = str(data.get("stdout") or "").strip()
                    err = str(data.get("stderr") or "").strip()
                    parts = [f"exit_code: {code}"]
                    if err:
                        parts.append(f"stderr (errors/warnings):\n{err[-800:]}")
                    if out:
                        out_lines = out.splitlines()
                        if len(out_lines) > 20:
                            head_part = "\n".join(out_lines[:10])
                            tail_part = "\n".join(out_lines[-8:])
                            parts.append(
                                f"stdout:\n{head_part}\n... [{len(out_lines) - 18} lines condensed by ACON] ...\n{tail_part}"
                            )
                        else:
                            parts.append(f"stdout:\n{out}")
                    return json.dumps(
                        {
                            "exit_code": code,
                            "acon_optimized": True,
                            "output": "\n\n".join(parts)[:limit],
                        },
                        ensure_ascii=False,
                    )
            except Exception:
                pass

        # Rule 3: File search / grep / glob results: preserve matches count & top hits
        if tool_name in {"search_files", "grep", "glob", "list_files"}:
            try:
                data = json.loads(raw)
                if (
                    isinstance(data, dict)
                    and "matches" in data
                    and isinstance(data["matches"], list)
                ):
                    matches = data["matches"]
                    condensed = matches[:15]
                    return json.dumps(
                        {
                            "total_matches": len(matches),
                            "acon_condensed": len(matches) > 15,
                            "matches": condensed,
                        },
                        ensure_ascii=False,
                    )
            except Exception:
                pass

        # Default ACON context compression: Action-Centric head (intent & state) + tail (result & return)
        head_len = max(200, int(limit * 0.4))
        tail_len = max(150, int(limit * 0.35))
        omitted = len(raw) - head_len - tail_len
        return (
            raw[:head_len]
            + f"\n\n... [ACON: {omitted} chars compressed to optimize context for long-horizon agent] ...\n\n"
            + raw[-tail_len:]
        )


class HistoryOptimizer:
    """ACON History Optimizer (ctxopt.history_optimizer).

    Summarizes long-horizon agent interaction history into structured
    state representations while preserving action-observation causality.
    """

    def __init__(self, threshold_chars: int = 4000) -> None:
        self.threshold_chars = threshold_chars

    def check_summarization_needed(
        self, history_text: str, prev_summary: str | None = None, threshold: int | None = None
    ) -> bool:
        th = self.threshold_chars if threshold is None else threshold
        total_len = len(history_text) + (len(prev_summary) if prev_summary else 0)
        return total_len > th

    def optimize_history(
        self,
        task: str,
        messages: list[dict[str, Any]],
        prev_summary: str | None = None,
        llm_summarizer: Callable[[str], str] | None = None,
    ) -> str:
        """Condense history into dense task state according to ACON schema."""
        if llm_summarizer:
            history_text = "\n\n".join(
                f"[{m.get('role', 'user').upper()}]: {m.get('content', '')[:1000]}"
                for m in messages
            )
            prompt = f"Task: {task}\n"
            if prev_summary:
                prompt += f"<PREVIOUS_SUMMARY>\n{prev_summary}\n</PREVIOUS_SUMMARY>\n"
            prompt += f"<HISTORY>\n{history_text}\n</HISTORY>\n\n" + COMPACTION_INSTRUCTION
            try:
                res = llm_summarizer(prompt)
                if res and res.strip():
                    return res.strip()
            except Exception:
                pass
        return build_session_memory_summary(messages, previous_summary=prev_summary or "")
