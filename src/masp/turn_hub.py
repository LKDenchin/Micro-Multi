"""Backend-owned turns: subscribers may disconnect without cancelling work."""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class LiveTurn:
    message_id: str
    frames: deque[tuple[int, str]] = field(default_factory=deque)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    sequence: int = 0
    bytes: int = 0
    finished_at: float | None = None

    def publish(self, frame: str) -> None:
        self.sequence += 1
        self.frames.append((self.sequence, frame))
        self.bytes += len(frame.encode("utf-8"))
        while self.bytes > 8 * 1024 * 1024 and len(self.frames) > 1:
            _, oldest = self.frames.popleft()
            self.bytes -= len(oldest.encode("utf-8"))
        self.changed.set()

    async def subscribe(self, after: int = 0) -> AsyncIterator[str]:
        while True:
            self.changed.clear()
            if self.frames and after < self.frames[0][0] - 1:
                yield 'event: replay_reset\ndata: {"resync":true}\n\n'
                after = self.frames[0][0] - 1
            for sequence, frame in list(self.frames):
                if sequence > after:
                    after = sequence
                    yield f"id: {sequence}\n" + frame
            if self.finished_at is not None:
                return
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=10)
            except TimeoutError:
                yield ": heartbeat\n\n"


class TurnHub:
    def __init__(self) -> None:
        self.turns: dict[str, LiveTurn] = {}

    def running(self, conversation_id: str) -> bool:
        turn = self.turns.get(conversation_id)
        return turn is not None and turn.finished_at is None

    def start(self, conversation_id: str, message_id: str, source: AsyncIterator[str]) -> LiveTurn:
        if self.running(conversation_id):
            raise ValueError("Conversation already has an active turn")
        # Finished replay buffers expire; active autonomous work is never evicted.
        self.turns = {
            key: turn
            for key, turn in self.turns.items()
            if turn.finished_at is None or time.monotonic() - turn.finished_at < 600
        }
        finished = sorted(
            (turn.finished_at, key)
            for key, turn in self.turns.items()
            if turn.finished_at is not None
        )
        while len(finished) > 8:
            _, key = finished.pop(0)
            self.turns.pop(key, None)
        turn = LiveTurn(message_id)
        self.turns[conversation_id] = turn

        async def produce() -> None:
            try:
                async for frame in source:
                    turn.publish(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                turn.publish(
                    'event: error\ndata: {"detail":"Turn producer failed; progress is saved"}\n\n'
                )
            finally:
                turn.finished_at = time.monotonic()
                turn.changed.set()
                asyncio.get_running_loop().call_later(600, self._expire, conversation_id, turn)

        turn.task = asyncio.create_task(produce(), name="chat-turn-" + message_id)
        return turn

    def _expire(self, conversation_id: str, turn: LiveTurn) -> None:
        if self.turns.get(conversation_id) is turn and turn.finished_at is not None:
            self.turns.pop(conversation_id, None)

    async def close(self) -> None:
        tasks = [turn.task for turn in self.turns.values() if turn.task and not turn.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.turns.clear()
