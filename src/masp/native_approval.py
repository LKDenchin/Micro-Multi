"""Thread-to-event-loop bridge for exact native Harness approval requests."""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from contextvars import ContextVar
from typing import Any


class NativeApprovalBridge:
    def __init__(
        self,
        authorize: Callable[[dict[str, Any]], Awaitable[bool]],
        remaining: Callable[[], float],
        cancelled: Callable[[], bool],
    ):
        self.loop = asyncio.get_running_loop()
        self.authorize = authorize
        self.remaining = remaining
        self.cancelled = cancelled
        self.pending: dict[str, Future[bool]] = {}
        self.lock = threading.Lock()
        self.closed = False
        self.cancelled_ids: set[str] = set()

    def ask(self, event: dict[str, Any]) -> str:
        if self.loop.is_closed():
            return "unavailable"

        async def decide() -> bool:
            return await self.authorize(event)

        future: Future[bool] = asyncio.run_coroutine_threadsafe(decide(), self.loop)
        with self.lock:
            self.pending[event["approvalId"]] = future
            if self.closed or event["approvalId"] in self.cancelled_ids:
                future.cancel()
        try:
            approved = future.result(timeout=max(0.01, min(600, self.remaining())))
            return "allowed-once" if approved else ("cancelled" if self.cancelled() else "rejected")
        except Exception:
            future.cancel()
            return "cancelled" if self.cancelled() else "unavailable"
        finally:
            with self.lock:
                self.pending.pop(event["approvalId"], None)

    def cancel(self, identity: str) -> None:
        with self.lock:
            self.cancelled_ids.add(identity)
            future = self.pending.get(identity)
        if future:
            future.cancel()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            futures = list(self.pending.values())
        for future in futures:
            future.cancel()


native_approval: ContextVar[NativeApprovalBridge | None] = ContextVar(
    "native_approval", default=None
)
