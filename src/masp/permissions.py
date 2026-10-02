"""Exact-operation approvals shared by lead, workers and extension routers."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from masp.storage import Store, identifier, now

READ_TOOLS = {
    "read_file",
    "read_workspace_file",
    "list_files",
    "list_workspace_files",
    "search_files",
    "search_workspace_code",
    "grep",
    "glob",
    "glob_workspace_files",
    "web_search",
    "web_fetch",
    "list_skills",
    "load_skill",
    "read_skill_resource",
    "memory_search",
    "core_memory_get",
    "recall_memory_search",
    "workspace_info",
    "git_status",
    "git_diff",
    "archival_memory_search",
    "create_subagent",
    "adjust_subagent",
    "dispatch_subagent_task",
    "dispatch_subagents_parallel",
    "start_subagents",
    "wait_subagents",
    "configure_team",
}
FILE_TOOLS = {
    "write_file",
    "edit_file",
    "write_workspace_file",
    "edit_workspace_file",
    "delete_file",
    "memory_store",
    "memory_update",
    "memory_delete",
    "core_memory_append",
    "core_memory_replace",
    "archival_memory_insert",
}


def required_permission(name: str) -> str | None:
    if name in READ_TOOLS:
        return None
    return "files" if name in FILE_TOOLS else "commands"


class ApprovalBroker:
    def __init__(self, store: Store):
        self.store = store
        self.pending: dict[str, tuple[str, asyncio.Future[bool]]] = {}
        for record in store.list("approval"):
            if record.get("status") == "pending":
                store.update("approval", record["id"], status="interrupted")

    async def authorize(
        self,
        conversation_id: str,
        name: str,
        arguments: str,
        mode: str,
        cancel: asyncio.Event,
        emit: Callable[[str, dict[str, Any]], Any],
        capability_name: str | None = None,
    ) -> bool:
        required = required_permission(capability_name or name)
        if required is None or mode == "commands" or (mode == "files" and required == "files"):
            return True
        approval_id = identifier("approval")
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.pending[approval_id] = (conversation_id, future)
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        record = {
            "id": approval_id,
            "conversation_id": conversation_id,
            "status": "pending",
            "tool": name,
            "arguments": arguments,
            "required_mode": required,
            "created_at": now(),
        }
        self.store.put("approval", record, conversation_id)
        event = {
            **record,
            "approval_id": approval_id,
            "label": name,
            "path": args.get("path", ""),
            "command": args.get("command", ""),
            "reason": "需要用户确认本次操作；不会提升默认权限",
        }
        cancel_wait = asyncio.create_task(cancel.wait())
        try:
            await emit("approval_required", event)
            waitables: set[asyncio.Future[Any]] = {future, cancel_wait}
            done, _ = await asyncio.wait(
                waitables, timeout=600, return_when=asyncio.FIRST_COMPLETED
            )
            if future in done:
                return future.result()
            self.store.update(
                "approval", approval_id, status="cancelled" if cancel.is_set() else "expired"
            )
            return False
        finally:
            self.pending.pop(approval_id, None)
            if self.store.get("approval", approval_id).get("status") == "pending":
                self.store.update("approval", approval_id, status="cancelled")
            cancel_wait.cancel()
            if not future.done():
                future.cancel()
            await asyncio.gather(cancel_wait, return_exceptions=True)

    def decide(self, conversation_id: str, approval_id: str, allow: bool, mode: str) -> None:
        pending = self.pending.get(approval_id)
        if not pending or pending[0] != conversation_id or pending[1].done():
            raise ValueError("请求已结束或不属于当前对话")
        record = self.store.get("approval", approval_id)
        if allow and mode not in {"files", "commands"}:
            raise ValueError("授权范围无效")
        if allow and record["required_mode"] == "commands" and mode != "commands":
            raise ValueError("本次操作需要命令权限")
        self.store.update(
            "approval", approval_id, status="approved" if allow else "rejected", decided_at=now()
        )
        pending[1].set_result(allow)
