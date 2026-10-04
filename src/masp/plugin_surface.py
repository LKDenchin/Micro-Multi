"""Generic installed DSH client surfaces and their native Host connection."""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import anyio

from masp.cordis_runtime import CordisWorker, composed_manifest
from masp.native_process import native_creation_flags
from masp.storage import Store

_lock = threading.RLock()
_build_lock = threading.RLock()
_hosts: dict[tuple[str, str], CordisWorker] = {}
NATIVE = Path(__file__).parent / "native"


def surface_bundle(store: Store, plugin_id: str) -> dict[str, Any]:
    bundle = store.get("dsh_bundle", plugin_id)
    if not bundle.get("enabled"):
        raise ValueError("请先启用插件")
    if not bundle.get("native_manifest"):
        raise ValueError("此扩展没有 DSH Host")
    return bundle


def runtime_revision() -> str:
    digest = hashlib.sha256()
    for file in sorted(NATIVE.rglob("*.mjs")):
        digest.update(str(file.relative_to(NATIVE)).encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()[:24]


def surface_info(store: Store, plugin_id: str, home: Path | None = None) -> dict[str, Any]:
    bundle = surface_bundle(store, plugin_id)
    client = bundle["native_manifest"].get("client")
    capabilities = (
        surface_host(store, home, plugin_id).request("plugin-capabilities", pluginId=plugin_id)
        if home
        else {}
    )
    return {
        "available": bool(client),
        "client": client,
        "client_revision": client_revision(Path(bundle["native_manifest"]["root"])),
        "name": bundle["name"],
        "provides_models": bool(capabilities.get("providesModels")),
        "settings_namespaces": capabilities.get("settingsNamespaces", []),
    }


def surface_host(store: Store, home: Path, plugin_id: str) -> CordisWorker:
    surface_bundle(store, plugin_id)
    manifest = {**composed_manifest(store), "_runtimeRevision": runtime_revision()}
    signature = json.dumps(manifest, sort_keys=True)
    key = (str(store.path.resolve()), "*")
    with _lock:
        worker = _hosts.get(key)
        if worker and (worker.process.poll() is not None or worker.signature != signature):
            worker.close()
            del _hosts[key]
            worker = None
        if not worker:
            if len(_hosts) >= 8:
                raise ValueError("插件配置 Host 数量已达上限，请关闭不使用的插件")
            worker = CordisWorker(home, manifest, home)
            _hosts[key] = worker
        return worker


def close_surfaces(store: Store | None = None, plugin_id: str | None = None) -> None:
    with _lock:
        for key, worker in list(_hosts.items()):
            if (store is None or key[0] == str(store.path.resolve())) and (
                plugin_id is None or key[1] in {plugin_id, "*"}
            ):
                worker.close()
                del _hosts[key]


atexit.register(close_surfaces)


async def rpc_stream(
    store: Store, home: Path, plugin_id: str, body: dict[str, Any]
) -> AsyncGenerator[str, None]:
    worker = await asyncio.to_thread(surface_host, store, home, plugin_id)
    stream_id = uuid.uuid4().hex
    events: queue.Queue[dict[str, Any]] = queue.Queue()
    with worker.pending_lock:
        worker.stream_events[stream_id] = events
    work = asyncio.create_task(
        worker.request_async(
            "plugin-rpc-stream",
            timeout=86400,
            streamId=stream_id,
            channel=body.get("channel"),
            method=body.get("method"),
            payload=body.get("payload"),
        )
    )
    try:
        while not work.done() or not events.empty():
            try:
                packet = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            yield json.dumps({"value": packet["value"]}, ensure_ascii=False) + "\n"
        await work
    except Exception as error:
        yield json.dumps({"error": {"message": str(error)}}, ensure_ascii=False) + "\n"
    finally:
        await finish_stream(worker, stream_id, work)


async def finish_stream(worker: CordisWorker, stream_id: str, work: asyncio.Task[Any]) -> None:
    # Starlette cancels a disconnecting response inside an AnyIO scope. Cleanup
    # must survive that cancellation before deciding the shared Host is stuck.
    with anyio.CancelScope(shield=True):
        try:
            worker.control("cancel-call", id=stream_id)
        except (OSError, ValueError):
            pass
        with worker.pending_lock:
            worker.stream_events.pop(stream_id, None)
        try:
            await asyncio.wait_for(asyncio.shield(work), 5)
        except TimeoutError:
            # A page subscription has no authority to stop every installed
            # plugin. Release this waiter; the native abort remains in force.
            work.cancel()
        except (asyncio.CancelledError, ValueError, RuntimeError):
            pass
        await asyncio.gather(work, return_exceptions=True)


def client_revision(root: Path) -> str:
    package = root / "package.json"
    # Include installed client sources and adapter changes in the cache generation.
    digest = hashlib.sha256(package.read_bytes())
    for directory, folders, filenames in os.walk(root):
        folders[:] = sorted(
            name
            for name in folders
            if name not in {"node_modules", ".git"} and not (Path(directory) / name).is_symlink()
        )
        for name in sorted(filenames):
            file = Path(directory) / name
            stat = file.stat()
            digest.update(f"{file.relative_to(root)}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    digest.update(runtime_revision().encode())
    dependency_lock = NATIVE.parents[2] / "package-lock.json"
    if dependency_lock.is_file():
        digest.update(dependency_lock.read_bytes())
    return digest.hexdigest()[:24]


def client_asset(store: Store, home: Path, plugin_id: str, asset: str) -> Path:
    if asset not in {"client.js", "client.css"}:
        raise ValueError("不支持的插件页面资源")
    bundle = surface_bundle(store, plugin_id)
    manifest = bundle["native_manifest"]
    if not manifest.get("client"):
        raise ValueError("此插件没有浏览器界面")
    root = Path(manifest["root"]).resolve()
    output = home / "plugin-client-cache" / client_revision(root)
    with _build_lock:
        if not (output / "client.js").is_file():
            node = os.environ.get("MICRO_MULTI_NODE") or shutil.which("node")
            if not node:
                raise ValueError("插件页面需要 Node.js 运行环境")
            env = {**os.environ, "ELECTRON_RUN_AS_NODE": "1"}
            result = subprocess.run(
                [node, str(NATIVE / "build_plugin_client.mjs"), str(root), str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                env=env,
                creationflags=native_creation_flags(),
            )
            if result.returncode:
                raise ValueError("插件页面依赖未就绪：" + result.stderr[-3000:])
        file = output / asset
        if asset == "client.css" and not file.exists():
            file.write_text("", encoding="utf-8")
        return file
