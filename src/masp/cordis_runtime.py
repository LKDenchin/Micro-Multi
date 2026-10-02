"""Native Cordis Host subprocesses; no JavaScript runs in the renderer/backend."""

from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from masp.native_approval import NativeApprovalBridge, native_approval
from masp.native_process import ProcessJob, native_creation_flags
from masp.storage import Store

HOST = Path(__file__).parent / "native" / "cordis_host.mjs"
PREFIX = "MICRO_MULTI_CORDIS:"
MAX_WORKERS = 8
_workers: dict[tuple[str, str, str], CordisWorker] = {}
_guard = threading.RLock()


def native_manifest(root: Path) -> dict[str, Any] | None:
    """Accept built local Cordis packages or an explicit multi-plugin Host manifest."""
    package = root / "package.json"
    if not package.is_file():
        return None
    if package.is_symlink() or package.stat().st_size > 1_000_000:
        raise ValueError("Native package manifest exceeds size limit or is a symlink")
    data = json.loads(package.read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("package.json must be an object")
    native = (
        data.get("microMulti", {}).get("cordis")
        if isinstance(data.get("microMulti"), dict)
        else None
    )
    dsh = data.get("dsh", {}) if isinstance(data.get("dsh"), dict) else {}
    bundle = dsh.get("bundle", {}) if isinstance(dsh.get("bundle"), dict) else {}
    if bundle.get("patch"):
        paths = bundle["patch"] if isinstance(bundle["patch"], list) else [bundle["patch"]]
        if not paths or not all(isinstance(path, str) for path in paths):
            raise ValueError("dsh.bundle.patch must be a path or path list")
        normalized_paths = []
        for path in paths:
            file = (root / path).resolve()
            if (
                not file.is_relative_to(root.resolve())
                or not file.is_file()
                or file.stat().st_size > 1_000_000
            ):
                raise ValueError("Bundle patch must exist inside its package")
            normalized_paths.append(str(file))
        return {
            "root": str(root.resolve()),
            "plugins": [
                {
                    "bundlePaths": normalized_paths,
                    "packageName": str(data.get("name", "")),
                    "entry": None,
                }
            ],
            "client": dsh.get("client"),
        }
    dependencies = {**data.get("dependencies", {}), **data.get("peerDependencies", {})}
    if (
        native is None
        and not dsh
        and not any(name in dependencies for name in ("@deepseek-ai/cordis", "cordis"))
    ):
        return None
    if native is not None and not isinstance(native, dict):
        raise ValueError("microMulti.cordis must be an object")
    native = native or {}
    if native.get("client"):
        raise ValueError("This host cannot execute browser Client plugins")
    exported = data.get("exports", {})
    entry = native.get("entry") or data.get("main")
    if not entry:
        if isinstance(exported, dict):
            exported = exported.get(".", exported)
        if isinstance(exported, dict):
            entry = exported.get("import") or exported.get("default")
        elif isinstance(exported, str):
            entry = exported
    plugins = native.get("plugins") or [{"entry": entry, "config": native.get("config", {})}]
    if not isinstance(plugins, list) or not 1 <= len(plugins) <= 50:
        raise ValueError("Native bundle must contain 1 to 50 Host plugins")
    resolved = root.resolve()
    normalized = []
    for item in plugins:
        if not isinstance(item, dict) or not isinstance(item.get("entry"), str):
            raise ValueError(
                "Native plugin requires a built JavaScript entry; build the package first"
            )
        file = (resolved / item["entry"]).resolve()
        if (
            not file.is_relative_to(resolved)
            or not file.is_file()
            or file.suffix not in {".js", ".mjs", ".cjs", ".ts", ".mts"}
        ):
            raise ValueError("Native entry must be a local JS/TS file inside the package")
        if not isinstance(item.get("config", {}), dict):
            raise ValueError("Native plugin config must be an object")
        normalized.append(
            {"entry": str(file.relative_to(resolved)), "config": item.get("config", {})}
        )
    return {"root": str(resolved), "plugins": normalized}


class CordisWorker:
    def __init__(self, home: Path, manifest: dict[str, Any], workspace: Path):
        node = os.environ.get("MICRO_MULTI_NODE") or shutil.which("node")
        if not node:
            raise ValueError("Native Cordis requires Node.js 24+ (or MICRO_MULTI_NODE)")
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.pending: dict[
            int, tuple[queue.Queue[dict[str, Any]], NativeApprovalBridge | None]
        ] = {}
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.counter = 0
        self.closing = False
        self.last_used = time.monotonic()
        self.last_heartbeat = self.last_used
        self.signature = json.dumps(manifest, sort_keys=True)
        self.profile_signature = json.dumps(manifest.get("profile"), sort_keys=True)
        logdir = home / "cordis-logs"
        logdir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256((manifest["root"] + str(workspace)).encode()).hexdigest()[:16]
        self.logpath = logdir / (digest + ".log")
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "HOME",
                "USERPROFILE",
                "LANG",
                "APPDATA",
                "LOCALAPPDATA",
                "COMSPEC",
                "PATHEXT",
                "PROGRAMFILES",
            }
        }
        env["MICRO_MULTI_WORKSPACE"] = str(workspace)
        env["ELECTRON_RUN_AS_NODE"] = "1"
        self.process = subprocess.Popen(
            [node, "--max-old-space-size=256", str(HOST)],
            cwd=workspace,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=native_creation_flags(),
            start_new_session=sys.platform != "win32",
        )
        try:
            self.job = ProcessJob(int(getattr(self.process, "_handle", 0)))
        except OSError:
            self.process.kill()
            self.process.wait()
            raise
        self.readers = [
            threading.Thread(target=self._read, args=(error,), daemon=True)
            for error in (False, True)
        ]
        for reader in self.readers:
            reader.start()
        try:
            profile = manifest.get("profile")
            if profile:
                invocation_paths = json.loads(os.environ.get("MICRO_MULTI_NATIVE_PATCHES", "[]"))
                if not isinstance(invocation_paths, list) or not all(
                    isinstance(path, str) for path in invocation_paths
                ):
                    raise ValueError(
                        "MICRO_MULTI_NATIVE_PATCHES must be a JSON list of patch paths"
                    )
                profile = {**profile, "invocationPatchPaths": invocation_paths}
            self.inventory = self.request(
                "init",
                root=manifest["root"],
                plugins=manifest["plugins"],
                workspace=str(workspace),
                sessionRoot=str(home),
                profile=profile,
                skillRoots=manifest.get("skillRoots", []),
                allowPending=bool(manifest.get("allowPending")),
            )
        except Exception:
            self.close(graceful=False)
            raise

    def _log(self, value: str) -> None:
        # One bounded diagnostic file per bundle/workspace, never an unbounded pipe.
        try:
            with self.lock_for_log:
                if self.logpath.exists() and self.logpath.stat().st_size > 1_000_000:
                    self.logpath.write_text("[older diagnostics truncated]\n", encoding="utf-8")
                with self.logpath.open("a", encoding="utf-8") as output:
                    output.write(value[:8000] + "\n")
        except OSError:
            pass

    lock_for_log = threading.Lock()

    def _read(self, error_stream: bool) -> None:
        stream = self.process.stderr if error_stream else self.process.stdout
        assert stream is not None
        while line := stream.readline(524288):
            value = line.decode("utf-8", errors="replace").rstrip()
            if not error_stream and value.startswith(PREFIX):
                try:
                    packet = json.loads(value[len(PREFIX) :])
                    if packet.get("event") == "heartbeat":
                        self.last_heartbeat = time.monotonic()
                    elif packet.get("event") in {"bridge", "chat-event"}:
                        self.events.put(packet)
                    elif packet.get("event") == "approval":
                        with self.pending_lock:
                            target = self.pending.get(packet.get("requestId"))
                        bridge = target[1] if target else None

                        def answer(
                            event: dict[str, Any] = packet,
                            current: NativeApprovalBridge | None = bridge,
                        ) -> None:
                            outcome = current.ask(event) if current else "unavailable"
                            try:
                                self.control(
                                    "approval-response",
                                    approvalId=event["approvalId"],
                                    outcome=outcome,
                                )
                            except (OSError, ValueError):
                                pass

                        threading.Thread(target=answer, daemon=True).start()
                    elif packet.get("event") == "approval_cancel":
                        with self.pending_lock:
                            target = self.pending.get(packet.get("requestId"))
                        if target and target[1]:
                            target[1].cancel(packet["approvalId"])
                    else:
                        with self.pending_lock:
                            target = self.pending.get(packet.get("id"))
                        if target:
                            target[0].put(packet)
                except ValueError:
                    self.fail_pending("Malformed Cordis worker response")
            else:
                self._log(value)
        if not error_stream:
            self.fail_pending("Native Cordis process exited; inspect " + str(self.logpath))

    def fail_pending(self, error: str) -> None:
        with self.pending_lock:
            recipients = list(self.pending.items())
        for identity, (response, _bridge) in recipients:
            response.put({"id": identity, "error": error})

    def control(self, action: str, **payload: Any) -> None:
        data = json.dumps({"action": action, **payload}, ensure_ascii=False).encode("utf-8") + b"\n"
        if len(data) > 500000:
            raise ValueError("Cordis request exceeds 500 KB")
        with self.write_lock:
            assert self.process.stdin is not None
            self.process.stdin.write(data)
            self.process.stdin.flush()

    def request(self, action: str, timeout: float = 35, **payload: Any) -> dict[str, Any]:
        bridge = native_approval.get() if action == "call" else None
        response: queue.Queue[dict[str, Any]] = queue.Queue()
        with self.pending_lock:
            if self.closing and action != "dispose":
                raise RuntimeError("Native Cordis process is shutting down")
            if self.process.poll() is not None:
                raise RuntimeError(
                    "Native Cordis process is not running; retry explicitly to restart"
                )
            if len(self.pending) >= 32:
                raise RuntimeError("Native Cordis request capacity reached")
            self.counter += 1
            identity = self.counter
            self.pending[identity] = (response, bridge)
        try:
            self.last_used = time.monotonic()
            self.control(action, id=identity, **payload)
            self.last_heartbeat = time.monotonic()
            deadline = time.monotonic() + timeout
            cancel_sent = False
            while True:
                if bridge and time.monotonic() - self.last_heartbeat > 30:
                    raise queue.Empty("Native event loop stopped responding")
                if bridge and bridge.cancelled() and not cancel_sent:
                    self.control("cancel-call", id=identity)
                    deadline = min(deadline, time.monotonic() + 5)
                    cancel_sent = True
                try:
                    result = response.get(timeout=max(0.01, min(1, deadline - time.monotonic())))
                    break
                except queue.Empty:
                    if time.monotonic() >= deadline:
                        raise
            if result.get("error"):
                raise ValueError(result["error"])
            return dict(result["result"])
        except (queue.Empty, OSError) as error:
            self.close(graceful=False)
            raise TimeoutError(
                "Cordis host timed out or disconnected; process stopped, tool was not retried"
            ) from error
        finally:
            with self.pending_lock:
                self.pending.pop(identity, None)
            if bridge:
                bridge.close()

    def close(self, graceful: bool = True) -> None:
        with self.lock:
            with self.pending_lock:
                self.closing = True
            if self.process.poll() is None:
                if graceful:
                    try:
                        self.request("dispose", timeout=2)
                        assert self.process.stdin is not None
                        self.process.stdin.close()
                        self.process.wait(timeout=2)
                    except (
                        ValueError,
                        RuntimeError,
                        TimeoutError,
                        subprocess.TimeoutExpired,
                        OSError,
                    ):
                        pass
                if self.process.poll() is None:
                    if sys.platform == "win32" and self.job.handle:
                        self.job.close()
                    elif sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                            capture_output=True,
                            timeout=5,
                            creationflags=native_creation_flags(),
                        )
                    else:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            self.job.close()
            for reader in self.readers:
                if reader is not threading.current_thread():
                    reader.join(timeout=1)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream:
                    stream.close()


def composed_manifest(
    store: Store, extra: dict[str, Any] | None = None, bundle_id: str | None = None
) -> dict[str, Any]:
    manifests = {
        item["id"]: item["native_manifest"]
        for item in store.list("dsh_bundle")
        if item.get("enabled") and item.get("native_manifest") and item["id"] != bundle_id
    }
    if extra is not None:
        manifests[bundle_id or "default"] = extra
    plugins = [
        {**plugin, "root": manifest["root"], "bundleId": name}
        for name, manifest in sorted(manifests.items())
        for plugin in manifest["plugins"]
    ]
    enabled = {item["id"] for item in store.list("dsh_bundle") if item.get("enabled")}
    roots = sorted(
        {
            str(Path(item["path"]).parent.parent)
            for item in store.list("skill_owner")
            if item.get("bundle_id") in enabled and item.get("path") and not item.get("removed")
        }
    )
    roots.append(str(store.path.parent / "skills"))
    result = {
        "root": next(iter(manifests.values()))["root"] if manifests else str(store.path.parent),
        "plugins": plugins,
        "skillRoots": roots,
    }
    try:
        profile = store.get("native_profile", "active")
        config = Path(profile["configPath"])
        patches = [Path(path) for path in profile.get("patchPaths", [])]
        patches.extend(Path(path) for path in profile.get("layerPaths", []))
        home_patch = store.path.parent / "cordis.patch.yml"
        if home_patch.is_file():
            patches.append(home_patch)
        package = config.parent / "package.json"
        if package.is_file():
            patches.append(package)
        invocation = json.loads(os.environ.get("MICRO_MULTI_NATIVE_PATCHES", "[]"))
        patches.extend(Path(path) for path in invocation)
        result["profile"] = {
            **profile,
            "revision": hashlib.sha256(
                config.read_bytes()
                + json.dumps(invocation).encode()
                + b"".join(
                    str(path).encode() + (path.read_bytes() if path.is_file() else b"<missing>")
                    for path in patches
                )
            ).hexdigest(),
        }
    except KeyError:
        pass
    return result


def inspect_native(
    home: Path, manifest: dict[str, Any], store: Store | None = None, bundle_id: str | None = None
) -> dict[str, Any]:
    composed = composed_manifest(store, manifest, bundle_id) if store else manifest
    worker = CordisWorker(home, composed, Path(manifest["root"]))
    try:
        inventory = dict(worker.inventory)
        if store:
            previous_names = {
                item.get("native_tool")
                for item in store.list("plugin")
                if item.get("bundle_id") != bundle_id
                and item.get("runtime") == "native-cordis-host"
            }
            inventory["tools"] = [
                item for item in inventory["tools"] if item["name"] not in previous_names
            ]
            inventory["plugins"] = [
                item for item in inventory["plugins"] if item.get("bundleId") == bundle_id
            ]
        return inventory
    finally:
        worker.close()


def native_context_messages(
    contexts: list[dict[str, Any]], home: Path | None = None, *, images_as_text: bool = False
) -> list[dict[str, Any]]:
    """Project Harness blocks to provider messages; the complete source stays in the receipt."""
    messages: list[dict[str, Any]] = []
    for context in contexts:
        content = context.get("content", [])
        if isinstance(content, str):
            if content:
                messages.append({"role": "user", "content": content})
            continue
        blocks: list[dict[str, Any]] = []
        for block in content:
            if block.get("type") == "text":
                blocks.append({"type": "text", "text": block.get("text", "")})
            elif block.get("type") == "image":
                image = block.get("microMultiImage", {})
                try:
                    if home is None or block.get("offloaded"):
                        raise ValueError("image bytes unavailable or offloaded")
                    path = Path(image["path"]).resolve()
                    digest = image["sha256"]
                    if (
                        not path.is_relative_to((home / "native-contexts").resolve())
                        or path.name != digest
                    ):
                        raise ValueError("invalid native image transport path")
                    if path.stat().st_size > 10_000_000:
                        raise ValueError("image exceeds 10 MB")
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != digest or image["mediaType"] not in {
                        "image/png",
                        "image/jpeg",
                        "image/webp",
                        "image/gif",
                    }:
                        raise ValueError("native image digest or media type mismatch")
                    if images_as_text:
                        blocks.append(
                            {
                                "type": "text",
                                "text": "[Image available to Vision Router; use its vision tools with path: "
                                + str(path)
                                + "]",
                            }
                        )
                        continue
                    blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image['mediaType']};base64,"
                                + base64.b64encode(raw).decode("ascii"),
                            },
                        }
                    )
                except (KeyError, ValueError, OSError) as error:
                    blocks.append(
                        {
                            "type": "text",
                            "text": "[Native image "
                            + json.dumps(block.get("attachment", {}), ensure_ascii=False)
                            + f"; unavailable: {error}]",
                        }
                    )
            elif block.get("type") == "file":
                blocks.append(
                    {
                        "type": "text",
                        "text": "[Native file "
                        + json.dumps(block.get("attachment", {}), ensure_ascii=False)
                        + "; read-only path: "
                        + str(block.get("microMultiFilePath") or "unavailable")
                        + "]",
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "text",
                        "text": "[Native context block: "
                        + json.dumps(block, ensure_ascii=False)
                        + "]",
                    }
                )
        if blocks:
            messages.append(
                {
                    "role": "user",
                    "content": blocks
                    if any(b["type"] == "image_url" for b in blocks)
                    else "\n".join(b["text"] for b in blocks),
                }
            )
    return messages


class NativeToolFailure(ValueError):
    def __init__(self, contract: dict[str, Any]):
        self.contract = contract
        super().__init__(
            "Cordis tool failed: " + json.dumps(contract.get("error"), ensure_ascii=False)[:2000]
        )


class NativeToolOutput(str):
    """Text projection with the original Harness result retained for lifecycle consumers."""

    contract: dict[str, Any]

    def __new__(cls, text: str, contract: dict[str, Any]) -> NativeToolOutput:
        instance = super().__new__(cls, text)
        instance.contract = contract
        return instance


def execute_native(store: Store, plugin: dict[str, Any], arguments: str, workspace: Path) -> str:
    manifest = composed_manifest(store)
    manifest["allowPending"] = True
    key = (str(store.path.resolve()), "*", str(workspace.resolve()))
    with _guard:
        worker = _workers.get(key)
        if worker and (
            worker.process.poll() is not None
            or worker.profile_signature != json.dumps(manifest.get("profile"), sort_keys=True)
        ):
            worker.close()
            del _workers[key]
            worker = None
        if not worker:
            if len(_workers) >= MAX_WORKERS:
                raise RuntimeError(
                    "Native Cordis host limit reached (8); disable unused workspaces"
                )
            worker = CordisWorker(store.path.parent, manifest, workspace)
            _workers[key] = worker
    signature = json.dumps(manifest, sort_keys=True)
    with worker.lock:
        if worker.signature != signature:
            worker.request(
                "sync", plugins=manifest["plugins"], skillRoots=manifest.get("skillRoots", [])
            )
            worker.signature = signature
    bridge = native_approval.get()
    timeout = max(0.01, bridge.remaining()) if bridge else 35
    result = worker.request(
        "call",
        timeout=timeout,
        timeoutMs=int(timeout * 1000),
        approvalBridge=bridge is not None,
        name=plugin["native_tool"],
        arguments=json.loads(arguments or "{}"),
    )
    if result.get("isError"):
        raise NativeToolFailure(result)
    value = result.get("value")
    structured = value
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except ValueError:
            pass
    if (
        isinstance(structured, dict)
        and structured.get("ok") is False
        and structured.get("code")
        and structured.get("reason")
    ):
        failure = {
            **result,
            "isError": True,
            "error": {
                "message": structured["reason"],
                "code": structured["code"],
                "retryable": structured.get("retryable"),
            },
            "meta": {**(result.get("meta") or {}), "nativeIsError": False},
        }
        raise NativeToolFailure(failure)
    return NativeToolOutput(
        (
            json.dumps(value, ensure_ascii=False)
            if value is not None
            else "\n".join(
                item.get("text", "")
                for item in result.get("content", [])
                if item.get("type") == "text"
            )
        ),
        result,
    )


def close_native_hosts(store: Store | None = None, bundle_id: str | None = None) -> None:
    with _guard:
        keys = [key for key in _workers if store is None or key[0] == str(store.path.resolve())]
        if bundle_id is not None:
            for key in keys:
                worker = _workers[key]
                try:
                    worker.request("unmount", bundleId=bundle_id)
                    worker.signature = ""  # Reconcile current enabled inventory on next use.
                except (ValueError, RuntimeError, TimeoutError):
                    worker.close(graceful=False)
                    _workers.pop(key, None)
            return
        workers = [_workers.pop(key) for key in keys]
    for worker in workers:
        worker.close()


atexit.register(close_native_hosts)
