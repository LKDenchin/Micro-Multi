"""Cancelable ownership of only the processes spawned for one tool call."""

import asyncio
import inspect
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from masp.native_process import ProcessJob, native_creation_flags


def command_run(
    command: Any, *, cancel_signal: threading.Event, timeout: float, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    if cancel_signal.is_set():
        raise ValueError("Command cancelled")

    def decode(value: bytes) -> str:
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("gb18030" if sys.platform == "win32" else "utf-8", errors="replace")

    with (
        tempfile.TemporaryFile() as stdout,
        tempfile.TemporaryFile() as stderr,
        tempfile.TemporaryFile() as stdin,
    ):
        input_value = kwargs.get("input")
        if input_value is not None:
            stdin.write(
                input_value.encode("utf-8") if isinstance(input_value, str) else input_value
            )
            stdin.seek(0)
        process = subprocess.Popen(
            command,
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
            shell=kwargs.get("shell", False),
            stdout=stdout,
            stderr=stderr,
            stdin=stdin if input_value is not None else subprocess.DEVNULL,
            creationflags=native_creation_flags(),
            start_new_session=sys.platform != "win32",
        )
        job = None
        try:
            job = ProcessJob(int(getattr(process, "_handle", 0)), memory_bytes=None)
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel_signal.wait(0.05):
                    raise ValueError("Command cancelled")
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
            stdout.seek(0, os.SEEK_END)
            stdout.seek(max(0, stdout.tell() - 48_000))
            stderr.seek(0, os.SEEK_END)
            stderr.seek(max(0, stderr.tell() - 48_000))
            return subprocess.CompletedProcess(
                command, process.returncode, decode(stdout.read()), decode(stderr.read())
            )
        finally:
            if job:
                job.close()
            if process.poll() is None:
                if sys.platform == "win32":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


async def run_cancellable_tool(
    function: Any, *args: Any, cancel_event: asyncio.Event | None = None, **kwargs: Any
) -> Any:
    stop = threading.Event()
    if "cancel_signal" in inspect.signature(function).parameters:
        kwargs["cancel_signal"] = stop
    work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    watcher = asyncio.create_task(cancel_event.wait()) if cancel_event else None
    try:
        if watcher:
            await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if watcher.done():
                stop.set()
        return await asyncio.shield(work)
    finally:
        stop.set()
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if not work.done():
            await asyncio.gather(asyncio.shield(work), return_exceptions=True)
