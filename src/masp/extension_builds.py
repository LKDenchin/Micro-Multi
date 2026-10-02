"""Exact-source, single-use build approvals for acquired npm/Git packages."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from masp.extension_sources import discard_source, package_manager
from masp.native_process import ProcessJob, native_creation_flags
from masp.storage import Store, identifier, now

_guard = threading.Lock()


def run_build(command: dict[str, Any]) -> tuple[int, str]:
    output_file = tempfile.TemporaryFile()
    process = subprocess.Popen(
        command["argv"],
        cwd=command["cwd"],
        stdout=output_file,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=native_creation_flags(),
        start_new_session=sys.platform != "win32",
    )
    job = None
    try:
        job = ProcessJob(int(getattr(process, "_handle", 0)), memory_bytes=None)
        process.wait(timeout=240)
        output_file.seek(0, os.SEEK_END)
        output_file.seek(max(0, output_file.tell() - 16_000))
        output = output_file.read().decode("utf-8", errors="replace")
        return process.returncode, output[-4000:]
    finally:
        if job:
            job.close()
        if process.poll() is None:
            if sys.platform != "win32":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
        output_file.close()


def source_revision(root: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    # Include source scripts and manifests; omit acquired dependencies and Git internals.
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {"node_modules", ".git"})
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink():
                digest.update(str(path.relative_to(root)).encode("utf-8"))
                digest.update(os.readlink(path).encode("utf-8"))
        for filename in sorted(files):
            path = Path(directory) / filename
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            if path.is_symlink():
                digest.update(os.readlink(path).encode("utf-8"))
                continue
            total += path.stat().st_size
            if total > 64_000_000:
                raise ValueError("Build approval source exceeds 64 MB")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare_build(
    store: Store, home: Path, root: Path, stage: Path, source: str, error: str
) -> dict[str, Any] | None:
    package = root / "package.json"
    if not package.is_file():
        return None
    data = json.loads(package.read_text("utf-8"))
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict) or not isinstance(scripts.get("build"), str):
        return None
    manager, executable = package_manager(root)
    revision = source_revision(root)
    commands = [
        {
            "cwd": str(root),
            "argv": [executable, "run", "build"],
            "scripts": {
                key: scripts[key] for key in ("prebuild", "build", "postbuild") if key in scripts
            },
        }
    ]
    record = {
        "id": identifier("build"),
        "status": "pending",
        "name": data.get("name", source),
        "source": source,
        "root": str(root),
        "stage": str(stage),
        "revision": revision,
        "commands": commands,
        "manager": manager,
        "created_at": now(),
        "registration_error": error,
    }
    store.put("extension_build", record)
    return {**record, "status": "build_required"}


def approve_build(
    store: Store, home: Path, build_id: str, revision: str, approved: bool
) -> dict[str, Any]:
    """Never infer approval from commands permission or replay a failed build."""
    from masp.plugin_tools import _install_dsh_plugin_from_path

    with _guard:
        record = store.get("extension_build", build_id)
        if record["status"] != "pending" or record["revision"] != revision:
            raise ValueError("Build approval is stale or already consumed")
        root, stage = Path(record["root"]).resolve(), Path(record["stage"]).resolve()
        base = (home / "extension-sources").resolve()
        if stage.parent != base or not root.is_relative_to(stage):
            raise ValueError("Build path is outside managed sources")
        if not approved:
            store.update("extension_build", build_id, status="rejected", decided_at=now())
            discard_source(home, stage)
            return {"status": "rejected", "id": build_id}
        if source_revision(root) != revision:
            raise ValueError("Source changed after the build plan; acquire a new plan")
        store.update("extension_build", build_id, status="running", decided_at=now())
    try:
        outputs = []
        for command in record["commands"]:
            returncode, output = run_build(command)
            outputs.append(output)
            if returncode:
                raise ValueError("Approved bundle build failed: " + outputs[-1])
        installed = _install_dsh_plugin_from_path(store, home, str(root))
        store.update(
            "extension_build",
            build_id,
            status="completed",
            completed_at=now(),
            output="\n".join(outputs),
        )
        return installed
    except Exception as error:
        store.update("extension_build", build_id, status="failed", error=str(error)[-4000:])
        raise
