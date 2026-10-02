"""Reproducible local HTTP model latency baseline; no external model or credentials."""

import asyncio
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from masp.supervisor import SupervisorManager  # noqa: E402


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        time.sleep(0.2)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        response = {
            "choices": [{"delta": {"content": "Analysis complete"}, "finish_reason": "stop"}]
        }
        self.wfile.write(("data: " + json.dumps(response) + "\n\ndata: [DONE]\n\n").encode())


async def benchmark(workspace, port):
    config = SimpleNamespace(
        model="fixture",
        api_key="",
        base_url=f"http://127.0.0.1:{port}/v1",
        temperature=0,
        max_output_tokens=512,
        timeout_seconds=10,
    )

    async def emit(*_args):
        pass

    async with httpx.AsyncClient(timeout=10) as client:
        kwargs = dict(
            client=client,
            default_config=config,
            load_model_config=lambda _: config,
            sub_tools=[],
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            recovery_max_attempts=0,
        )
        serial_manager = SupervisorManager(workspace, "serial")
        start = time.perf_counter()
        serial_reports = [
            await serial_manager.execute_subagent_task(name, "Explain recursion", **kwargs)
            for name in ("a", "b", "c", "lead")
        ]
        serial = time.perf_counter() - start
        manager = SupervisorManager(workspace, "parallel", max_concurrency=3)
        lead = SupervisorManager(workspace, "lead")
        start = time.perf_counter()
        manager.start_subagents(
            [{"subagent_name": name, "prompt": "Explain recursion"} for name in ("a", "b", "c")],
            **kwargs,
        )
        lead_report = await lead.execute_subagent_task("lead", "Explain recursion", **kwargs)
        reports = []
        while manager.background_tasks:
            reports.extend((await manager.wait_subagents(1))["reports"])
        parallel = time.perf_counter() - start
        assert all(
            report["status"] == "completed" for report in [*serial_reports, *reports, lead_report]
        )
        return {
            "method": "four identical local HTTP SSE requests; 200ms response latency",
            "external_model": False,
            "serial_seconds": round(serial, 4),
            "parallel_seconds": round(parallel, 4),
            "speedup": round(serial / parallel, 2),
            "worker_count": 3,
            "lead_concurrent": True,
            "completed_requests": 4,
            "worker_timings": [report["timing"] for report in reports],
        }


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(benchmark(Path(directory), server.server_port))
        target = Path(__file__).resolve().parents[1] / "evidence" / "collaboration-benchmark.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
