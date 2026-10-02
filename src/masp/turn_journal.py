"""Durable in-flight assistant turns. Commit each visible SSE event before delivery."""

import asyncio
import json
from typing import Any

from masp.storage import Store, now


class TurnJournal:
    def __init__(
        self,
        store: Store,
        conversation_id: str,
        message_id: str,
        created: str,
        model: str,
        enabled_logs: bool = True,
    ):
        self.store = store
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.logs = enabled_logs
        self.finished = False
        self.record: dict[str, Any] = {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": "",
            "created_at": created,
            "model": model,
            "execution_status": "running",
            "tool_events": [],
            "subagent_events": [],
            "segments": [],
        }
        self.save()
        store.update(
            "conversation",
            conversation_id,
            message_count=len(store.list("message", conversation_id)),
            execution_status="running",
            active_turn_id=message_id,
        )

    def save(self) -> None:
        self.record["checkpoint_at"] = now()
        self.store.put("message", self.record, self.conversation_id)

    async def _offload(self, function: Any, *args: Any) -> None:
        # A cancelled stream must finish its in-flight commit before closing the record.
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def consume_async(self, frame: str) -> None:
        await self._offload(self.consume, frame)

    async def close_async(self) -> None:
        await self._offload(self.close)

    def consume(self, frame: str) -> None:
        for block in frame.split("\n\n"):
            lines = block.splitlines()
            payload = "\n".join(line[5:].strip() for line in lines if line.startswith("data:"))
            if not payload:
                continue
            event = next((line[6:].strip() for line in lines if line.startswith("event:")), "")
            data = json.loads(payload)
            if event == "complete":
                self.finished = True
                continue
            if data.get("delta"):
                self.record["content"] += data["delta"]
                # A single text frame in fallback checkpoints renders the complete partial answer.
            elif event == "thinking":
                self.record["thinking"] = data
            elif event == "tool":
                self.record["tool_events"].append(data)
            elif event == "subagent_progress":
                events = self.record["subagent_events"]
                events[:] = [
                    item for item in events if item.get("agent_id") != data.get("agent_id")
                ]
                events.append(data)
            elif event == "team":
                self.store.update("conversation", self.conversation_id, team=data)
            elif event == "error":
                self.record["execution_error"] = data.get("detail")
            elif event == "aborted":
                self.record["aborted"] = True
            else:
                continue
            self.save()

    def close(self) -> None:
        current = self.store.get("message", self.message_id)
        status = "completed" if self.finished else "interrupted"
        if current.get("termination_reason") or current.get("execution_error"):
            status = "failed"
        if status == "interrupted":
            for agent in current.get("subagent_events", []):
                if agent.get("status") in {"running", "paused"}:
                    agent["status"] = "cancelled"
            self.store.update(
                "message", self.message_id, subagent_events=current.get("subagent_events", [])
            )
        self.store.update("message", self.message_id, execution_status=status, checkpoint_at=now())
        self.store.update(
            "conversation",
            self.conversation_id,
            message_count=len(self.store.list("message", self.conversation_id)),
            updated_at=now(),
            execution_status=status,
        )


def recover_interrupted_turns(store: Store) -> None:
    for message in store.list("message"):
        if message.get("execution_status") == "running":
            for agent in message.get("subagent_events", []):
                if agent.get("status") in {"running", "paused"}:
                    agent["status"] = "cancelled"
            store.update(
                "message",
                message["id"],
                execution_status="interrupted",
                subagent_events=message.get("subagent_events", []),
                interruption_reason="应用或连接退出，保留本轮已收到的内容",
            )
            store.update("conversation", message["conversation_id"], execution_status="interrupted")
