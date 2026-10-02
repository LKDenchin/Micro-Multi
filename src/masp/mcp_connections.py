"""MCP connection actors. Each SDK context is opened and closed by its owner task."""

import asyncio
import json
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

_pool: dict[tuple[Any, ...], "Connection"] = {}


class Connection:
    def __init__(
        self, key: tuple[Any, ...], connector: Callable[[], AbstractAsyncContextManager[Any]]
    ):
        self.key = key
        self.queue: asyncio.Queue[
            tuple[str, tuple[Any, ...], dict[str, Any], asyncio.Future[Any]]
        ] = asyncio.Queue()
        self.pending: set[asyncio.Future[Any]] = set()
        self.operations: set[asyncio.Task[None]] = set()
        self.last_used = time.monotonic()
        self.task = asyncio.create_task(self._run(connector), name="mcp-connection-" + str(key[1]))
        self.task.add_done_callback(
            lambda _: _pool.pop(key, None) if _pool.get(key) is self else None
        )

    async def _run(self, connector: Callable[[], AbstractAsyncContextManager[Any]]) -> None:
        failure: BaseException = RuntimeError(
            "MCP connection closed; the operation was not retried"
        )
        try:
            async with connector() as client:
                while True:
                    method, args, kwargs, future = await self.queue.get()
                    if future.cancelled():
                        continue

                    async def execute(
                        method: str = method,
                        args: tuple[Any, ...] = args,
                        kwargs: dict[str, Any] = kwargs,
                        future: asyncio.Future[Any] = future,
                    ) -> None:
                        try:
                            result = await getattr(client, method)(*args, **kwargs)
                            if not future.done():
                                future.set_result(result)
                        except asyncio.CancelledError:
                            if not future.done():
                                future.cancel()
                            raise
                        except Exception as error:
                            if not future.done():
                                future.set_exception(error)
                        finally:
                            self.pending.discard(future)

                    operation = asyncio.create_task(execute())
                    self.operations.add(operation)
                    operation.add_done_callback(self.operations.discard)

                    def cancel_operation(
                        done: asyncio.Future[Any], operation: asyncio.Task[None] = operation
                    ) -> None:
                        if done.cancelled():
                            operation.cancel()

                    future.add_done_callback(cancel_operation)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure = error
        finally:
            for operation in list(self.operations):
                operation.cancel()
            await asyncio.gather(*self.operations, return_exceptions=True)
            for future in self.pending:
                if not future.done():
                    future.set_exception(failure)
            self.pending.clear()

    async def request(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.last_used = time.monotonic()
        future = asyncio.get_running_loop().create_future()
        self.pending.add(future)
        self.queue.put_nowait((method, args, kwargs, future))
        return await future

    async def list_tools(self, **kwargs: Any) -> Any:
        return await self.request("list_tools", **kwargs)

    async def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        return await self.request("call_tool", *args, **kwargs)


def connection(
    server: dict[str, Any], cwd: Path, connector: Callable[[], AbstractAsyncContextManager[Any]]
) -> Connection:
    loop = asyncio.get_running_loop()
    signature = json.dumps(
        {
            key: server.get(key)
            for key in ("transport", "command", "args", "url", "env", "headers", "cwd")
        },
        sort_keys=True,
    )
    identity = str(
        server.get("id") or server.get("name") or server.get("url") or server.get("command")
    )
    key = (loop, identity, str(cwd.resolve()), signature)
    existing = _pool.get(key)
    if existing and not existing.task.done():
        return existing
    for old_key, previous in list(_pool.items()):
        if old_key[:3] == key[:3] and old_key != key:
            previous.task.cancel()
            _pool.pop(old_key, None)
    if len([item for item in _pool if item[0] is loop]) >= 32:
        idle = [item for item in _pool.values() if item.key[0] is loop and not item.pending]
        if not idle:
            raise RuntimeError("MCP connection capacity reached; all servers are busy")
        previous = min(idle, key=lambda item: item.last_used)
        previous.task.cancel()
        _pool.pop(previous.key, None)
    actor = Connection(key, connector)
    _pool[key] = actor
    return actor


async def close_connections() -> None:
    loop = asyncio.get_running_loop()
    actors = [actor for key, actor in list(_pool.items()) if key[0] is loop]
    for actor in actors:
        actor.task.cancel()
    await asyncio.gather(*(actor.task for actor in actors), return_exceptions=True)


def invalidate_connections(server_id: str) -> None:
    # Configuration and bundle toggles also run in synchronous API threads.
    for key, actor in list(_pool.items()):
        if key[1] == server_id and not key[0].is_closed():
            key[0].call_soon_threadsafe(actor.task.cancel)
