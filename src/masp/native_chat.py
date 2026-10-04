"""Async application bridge; the official Node AgentLoop owns turns and tools."""

from __future__ import annotations

import asyncio
import json
import queue
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from masp.cordis_runtime import CordisWorker, composed_manifest
from masp.model_runtime import (
    compatible_model_stream,
    complete_stream_result,
    configure_provider,
    merge_stream_identifier,
    model_stream_lines,
    requests_execution,
)
from masp.storage import Store


def provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for message in messages:
        blocks = message.get("content", [])
        text = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        role = message["role"]
        item: dict[str, Any] = {"role": role, "content": text}
        if role == "assistant":
            calls = [
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": block["arguments"]},
                }
                for block in blocks
                if block.get("type") == "tool-call"
            ]
            if calls:
                item["tool_calls"] = calls
            item["reasoning_content"] = "".join(
                block.get("text", "") for block in blocks if block.get("type") == "reasoning"
            )
        if role == "tool":
            item["tool_call_id"] = message["source"]["callId"]
        if role != "developer":
            projected.append(item)
    return projected


async def native_chat_events(
    store: Store,
    home: Path,
    workspace: Path,
    conversation_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    client: Any,
    config: Any,
    execute_tool: Callable[[str, str], Awaitable[str]],
    cancel_event: asyncio.Event,
    pause_event: asyncio.Event,
    *,
    max_steps: int,
    max_concurrency: int,
    remaining: Callable[[], float],
    authorize_tool: Callable[[str, str], Awaitable[bool]] | None = None,
    require_subagent: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    manifest = composed_manifest(store)
    manifest["allowPending"] = False
    worker = await asyncio.to_thread(CordisWorker, home, manifest, workspace)
    running: set[asyncio.Task[Any]] = set()
    completed = asyncio.Queue[tuple[str, dict[str, Any]]]()

    async def dispatch(packet: dict[str, Any]) -> None:
        bridge_id = packet["bridgeId"]
        try:
            data = packet["data"]
            while pause_event.is_set() and not cancel_event.is_set():
                await asyncio.sleep(0.05)
            if cancel_event.is_set():
                raise asyncio.CancelledError
            if packet["kind"] == "authorize":
                allowed = (
                    await authorize_tool(
                        data["name"], json.dumps(data["arguments"], ensure_ascii=False)
                    )
                    if authorize_tool
                    else False
                )
                worker.control("bridge-response", bridgeId=bridge_id, result=allowed)
                return
            if packet["kind"] == "tool":
                name = data["name"]
                arguments = json.dumps(data["arguments"], ensure_ascii=False)
                result = await execute_tool(name, arguments)
                worker.control("bridge-response", bridgeId=bridge_id, result={"text": str(result)})
                return
            payload = {
                "model": config.model,
                "stream": True,
                "messages": provider_messages(data["messages"]),
                "temperature": config.temperature,
                "max_tokens": data.get("maxTokens", config.max_output_tokens),
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters", {}),
                        },
                    }
                    for tool in data.get("tools", [])
                ],
            }
            if not payload["tools"]:
                payload.pop("tools")
            if "/api/dsh/plugins/" in config.base_url:
                payload["session_id"] = conversation_id
                selection = store.get("conversation", conversation_id).get("model_selection") or {}
                if selection.get("reasoningEffort") and config.model == json.dumps(
                    [selection.get("provider"), selection.get("model")], separators=(",", ":")
                ):
                    payload["reasoning_effort"] = selection["reasoningEffort"]
            configure_provider(payload, config.base_url, recovering=False)
            headers = {"Authorization": "Bearer " + config.api_key} if config.api_key else {}
            blocks: dict[int, dict[str, Any]] = {}
            calls: dict[int, dict[str, Any]] = {}

            def chunk(value: dict[str, Any]) -> None:
                worker.control("bridge-chunk", bridgeId=bridge_id, chunk=value)

            started = time.monotonic()
            finish = None
            async with (
                asyncio.timeout(max(0.01, min(remaining(), 900))),
                compatible_model_stream(
                    client,
                    "POST",
                    config.base_url + "/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response,
            ):
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Model HTTP {response.status_code}: "
                        + (await response.aread()).decode(errors="replace")[:200]
                    )
                async for line in model_stream_lines(response, float(config.timeout_seconds)):
                    if cancel_event.is_set():
                        raise asyncio.CancelledError
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        finish = finish or "stop"
                        break
                    try:
                        choices = json.loads(raw).get("choices") or []
                    except ValueError:
                        continue
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    finish = choices[0].get("finish_reason") or finish
                    for key, kind, index in (
                        ("reasoning_content", "reasoning", 0),
                        ("content", "text", 1),
                    ):
                        if delta.get(key):
                            if index not in blocks:
                                blocks[index] = {"type": kind, "text": ""}
                                chunk({"type": "block-start", "index": index, "blockType": kind})
                            blocks[index]["text"] += delta[key]
                            chunk({"type": kind + "-delta", "index": index, "text": delta[key]})
                    for call in delta.get("tool_calls") or []:
                        index = int(call.get("index", 0)) + 2
                        if index not in calls:
                            calls[index] = {
                                "type": "tool-call",
                                "id": call.get("id") or str(uuid.uuid4()),
                                "name": "",
                                "arguments": "",
                            }
                            chunk({"type": "block-start", "index": index, "blockType": "tool-call"})
                        fn = call.get("function") or {}
                        value = calls[index]
                        value["name"] = merge_stream_identifier(value["name"], fn.get("name", ""))
                        value["arguments"] += fn.get("arguments", "")
                        chunk(
                            {
                                "type": "tool-call-delta",
                                "index": index,
                                "id": value["id"],
                                "name": value["name"],
                                "argumentsDelta": fn.get("arguments", ""),
                            }
                        )
            if finish is None and complete_stream_result(
                "".join(block.get("text", "") for block in blocks.values()), calls
            ):
                finish = "tool_calls" if calls else "stop"
            if finish is None:
                raise RuntimeError("Model stream ended without a terminal frame")
            for index, block in sorted({**blocks, **calls}.items()):
                chunk({"type": "block-end", "index": index, "block": block})
            chunk(
                {
                    "type": "finish",
                    "reason": {
                        "kind": "max-tokens"
                        if finish == "length"
                        else "tool-calls"
                        if calls
                        else "stop"
                    },
                }
            )
            await completed.put(
                (
                    "native-model-step",
                    {
                        "duration_seconds": round(time.monotonic() - started, 4),
                        "finish_reason": finish,
                        "native_session_id": data.get("sessionId"),
                    },
                )
            )
            worker.control("bridge-response", bridgeId=bridge_id, result={})
        except BaseException as error:
            worker.control(
                "bridge-response",
                bridgeId=bridge_id,
                error="Cancelled"
                if isinstance(error, asyncio.CancelledError)
                else f"{type(error).__name__}: {error}",
            )

    prompt = str(messages[-1]["content"])
    if len(messages) > 2:
        prompt = (
            "Previous conversation (reference data):\n"
            + json.dumps(messages[1:-1], ensure_ascii=False)
            + "\nCurrent task:\n"
            + prompt
        )
    run = asyncio.create_task(
        asyncio.to_thread(
            worker.request,
            "chat-run",
            timeout=max(1, remaining()),
            conversationId=conversation_id,
            sessionId=conversation_id + "-" + uuid.uuid4().hex[:12],
            system=messages[0]["content"],
            prompt=prompt,
            tools=tools,
            model=config.model,
            maxTokens=int(config.max_output_tokens),
            maxSteps=max_steps,
            maxConcurrency=max_concurrency,
            requiresExecution=requests_execution(str(messages[-1]["content"])),
            requireSubagent=require_subagent,
        )
    )
    try:
        while not run.done() or not worker.events.empty() or not completed.empty():
            if cancel_event.is_set():
                worker.control("cancel-call", id=worker.counter)
            try:
                packet = await asyncio.to_thread(worker.events.get, True, 0.05)
                if packet["event"] == "bridge":
                    task = asyncio.create_task(dispatch(packet))
                    running.add(task)
                    task.add_done_callback(running.discard)
                else:
                    yield packet["kind"], packet["data"]
            except queue.Empty:
                pass
            while not completed.empty():
                yield completed.get_nowait()
        result = await run
        yield "native-runtime", result
    finally:
        worker.control("cancel-call", id=worker.counter)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await asyncio.to_thread(worker.close, False)
        await asyncio.gather(run, return_exceptions=True)
