"""Task-scoped workspace leases shared by lead and workers."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

owner: ContextVar[str] = ContextVar("workspace_owner", default="main")
lease_holder: ContextVar[str | None] = ContextVar("workspace_lease_holder", default=None)


class WorkspaceCoordinator:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.condition = asyncio.Condition()
        self.block_shell_deletion = True
        self.external_busy = False
        self.active: dict[str, list[Path]] = {}
        self.written: dict[Path, str] = {}
        self.pending: list[tuple[str, list[Path]]] = []

    def paths(self, scopes: list[str]) -> list[Path]:
        result = []
        for scope in scopes or ["."]:
            path = (self.root / scope).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError("任务路径必须位于当前工作区")
            result.append(path)
        return result

    @staticmethod
    def overlaps(left: list[Path], right: list[Path]) -> bool:
        return any(a.is_relative_to(b) or b.is_relative_to(a) for a in left for b in right)

    def reserve(self, identity: str, scopes: list[str]) -> None:
        if not any(who == identity for who, _ in self.pending):
            self.pending.append((identity, self.paths(scopes)))

    async def release_reservation(self, identity: str) -> None:
        async with self.condition:
            self.pending = [(who, paths) for who, paths in self.pending if who != identity]
            self.condition.notify_all()

    @asynccontextmanager
    async def lease(self, identity: str, scopes: list[str]) -> AsyncIterator[None]:
        paths = self.paths(scopes)
        self.reserve(identity, scopes)

        def ready() -> bool:
            if identity in self.active or any(
                self.overlaps(paths, held) for held in self.active.values()
            ):
                return False
            for who, earlier in self.pending:
                if who == identity:
                    return True
                if self.overlaps(paths, earlier):
                    return False
            return True

        try:
            async with self.condition:
                await self.condition.wait_for(ready)
                self.pending = [(who, queued) for who, queued in self.pending if who != identity]
                self.active[identity] = paths
        except BaseException:
            await self.release_reservation(identity)
            raise
        token = owner.set(identity)
        holder_token = lease_holder.set(identity)
        try:
            yield
        finally:
            lease_holder.reset(holder_token)
            owner.reset(token)
            async with self.condition:
                self.active.pop(identity, None)
                self.condition.notify_all()

    @asynccontextmanager
    async def operation(self, name: str, arguments: str) -> AsyncIterator[None]:
        if name in {
            "read_file",
            "list_files",
            "search_files",
            "web_search",
            "web_fetch",
            "memory_search",
            "mcp:get_run",
            "mcp:get_job",
            "mcp:cancel_run",
            "mcp:cancel_job",
        }:
            yield
            return
        if self.external_busy:
            raise PermissionError(
                "本轮外部生成任务尚未结束，先查询或取消它，不得并行改写同一工作区"
            )
        identity = owner.get()
        args: Any = json.loads(arguments or "{}")
        if (
            name == "run_command"
            and self.block_shell_deletion
            and isinstance(args, dict)
            and re.search(
                r"(?i)(?:\b(?:remove-item|rmdir|rd|rm|del|erase)\s|\b(?:rmtree|unlink|unlinkSync|rmdirSync)\s*\(|\b(?:os|fs)\s*\.\s*(?:remove|rm|rmSync)\s*\()",
                str(args.get("command", "")),
            )
        ):
            raise PermissionError("多代理清理不能使用不受文件归属检查的删除命令，请用 delete_file")
        path = (
            (self.root / str(args.get("path", "."))).resolve()
            if isinstance(args, dict)
            else self.root
        )
        held = self.active.get(identity) if lease_holder.get() == identity else None
        if (
            held
            and name in {"write_file", "edit_file", "delete_file"}
            and not any(path.is_relative_to(scope) for scope in held)
        ):
            raise PermissionError("文件不属于本任务的负责路径，请协调归属后再操作")

        def check_delete() -> None:
            if name == "delete_file" and path in self.written and self.written[path] != identity:
                raise PermissionError("禁止删除本轮其他代理已经产出的文件；请由文件作者处理")

        async def finish() -> None:
            if name in {"write_file", "edit_file"} and path.is_file():
                self.written[path] = identity
            elif name == "delete_file":
                self.written.pop(path, None)

        if held:
            check_delete()
            yield
            await finish()
        else:
            # Opaque commands/plugins use the entire workspace. Task leases prevent
            # directory cleanup from overlapping any lead/worker file creation.
            scopes = (
                [str(path.relative_to(self.root))]
                if name in {"write_file", "edit_file", "delete_file"}
                and path.is_relative_to(self.root)
                else ["."]
            )
            async with self.lease(identity, scopes):
                check_delete()
                yield
                await finish()
