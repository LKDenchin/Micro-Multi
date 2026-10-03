"""Translate application model requests to installed Cordis LLM providers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import queue
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from masp.plugin_surface import surface_bundle, surface_host
from masp.storage import Store, now


def import_models(store: Store, home: Path, plugin_id: str, base_url: str) -> dict[str, Any]:
    bundle = surface_bundle(store, plugin_id)
    catalog = surface_host(store, home, plugin_id).request("plugin-models", timeout=60)
    models = []
    base = base_url.rstrip("/") + "/api/dsh/plugins/" + quote(plugin_id, safe="") + "/models"
    for model in catalog["models"]:
        wire_model = json.dumps([model["provider"], model["id"]], separators=(",", ":"))
        identity = (
            "plugin-model-" + hashlib.sha256((plugin_id + wire_model).encode()).hexdigest()[:20]
        )
        record = {
            "id": identity,
            "name": (model.get("name") or model["id"]) + " · " + model["provider"],
            "base_url": base,
            "model": wire_model,
            "has_api_key": False,
            "temperature": 0.2,
            "top_p": 1.0,
            "max_output_tokens": min(32768, model.get("maxOutputTokens") or 8192),
            "timeout_seconds": 300,
            "plugin_id": plugin_id,
            "provider": model["provider"],
            "created_at": now(),
            "updated_at": now(),
        }
        models.append(store.put("model_profile", record))
    current = {model["id"] for model in models}
    for previous in store.list("model_profile"):
        if previous.get("plugin_id") == plugin_id and previous["id"] not in current:
            store.delete("model_profile", previous["id"])
    return {"models": models, "plugin": bundle["name"]}


def request_options(body: dict[str, Any]) -> dict[str, Any]:
    provider, model = json.loads(body["model"])
    if not isinstance(provider, str) or not isinstance(model, str):
        raise ValueError("无效的插件模型")
    messages = []
    for index, message in enumerate(body.get("messages", [])):
        role = message["role"]
        raw = message.get("content") or ""
        if isinstance(raw, str):
            content: list[dict[str, Any]] = [{"type": "text", "text": raw}]
        else:
            # Preserve text and inline images; offloaded attachments remain owned by the app.
            content = []
            for block in raw:
                if block.get("type") == "text":
                    content.append({"type": "text", "text": block["text"]})
                else:
                    raise ValueError("此插件模型桥接尚不支持该附件类型")
        if role == "tool":
            messages.append(
                {
                    "id": str(index),
                    "role": "tool",
                    "source": {"kind": "tool", "callId": message["tool_call_id"]},
                    "toolCallId": message["tool_call_id"],
                    "content": content,
                }
            )
            continue
        for call in message.get("tool_calls", []):
            content.append(
                {
                    "type": "tool-call",
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"],
                }
            )
        source = (
            {"kind": "model", "provider": provider, "model": model}
            if role == "assistant"
            else {"kind": "system-prompt"}
            if role == "system"
            else {"kind": "user"}
        )
        messages.append({"id": str(index), "role": role, "source": source, "content": content})
    return {
        "provider": provider,
        "model": model,
        "messages": messages,
        "tools": [tool["function"] for tool in body.get("tools", [])],
        "temperature": body.get("temperature", 0.2),
        "maxTokens": body.get("max_tokens", 8192),
        **({"reasoningEffort": body["reasoning_effort"]} if body.get("reasoning_effort") else {}),
    }


def openai_chunk(chunk: dict[str, Any], tool_indexes: dict[int, int]) -> dict[str, Any] | None:
    kind = chunk["type"]
    delta: dict[str, Any] = {}
    finish = None
    if kind == "text-delta":
        delta["content"] = chunk["text"]
    elif kind == "reasoning-delta":
        delta["reasoning_content"] = chunk["text"]
    elif kind == "tool-call-delta":
        index = tool_indexes.setdefault(chunk["index"], len(tool_indexes))
        function = {"arguments": chunk.get("argumentsDelta", "")}
        if chunk.get("name"):
            function["name"] = chunk["name"]
        delta["tool_calls"] = [
            {"index": index, "id": chunk["id"], "type": "function", "function": function}
        ]
    elif kind == "finish":
        if chunk["reason"] in {"error", "aborted"}:
            raise ValueError("插件模型请求失败或取消，请检查登录和插件配置")
        finish = "tool_calls" if tool_indexes else "stop"
    elif kind == "usage":
        usage = chunk["usage"]
        return {
            "choices": [],
            "usage": {
                "prompt_tokens": usage.get("inputTokens", 0),
                "completion_tokens": usage.get("outputTokens", 0),
            },
        }
    else:
        return None
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


async def completion_stream(
    store: Store, home: Path, plugin_id: str, body: dict[str, Any]
) -> AsyncIterator[str]:
    options = request_options(body)
    worker = await asyncio.to_thread(surface_host, store, home, plugin_id)
    stream_id = uuid.uuid4().hex
    events: queue.Queue[dict[str, Any]] = queue.Queue()
    with worker.pending_lock:
        worker.stream_events[stream_id] = events
    work = asyncio.create_task(
        asyncio.to_thread(worker.request, "plugin-model-stream", timeout=900, options=options, streamId=stream_id)
    )
    tool_indexes: dict[int, int] = {}
    try:
        while not work.done() or not events.empty():
            try:
                packet = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if packet.get("event") == "plugin-model-chunk":
                projected = openai_chunk(packet["chunk"], tool_indexes)
                if projected:
                    yield "data: " + json.dumps(projected, ensure_ascii=False) + "\n\n"
        await work
        yield "data: [DONE]\n\n"
    except Exception as error:
        yield "data: " + json.dumps({"error": {"message": str(error)}}, ensure_ascii=False) + "\n\n"
    finally:
        worker.control("cancel-call", id=stream_id)
        with worker.pending_lock:
            worker.stream_events.pop(stream_id, None)
        try:
            await asyncio.wait_for(asyncio.shield(work), 5)
        except (TimeoutError, asyncio.CancelledError):
            await asyncio.to_thread(worker.close, graceful=False)
        await asyncio.gather(work, return_exceptions=True)
