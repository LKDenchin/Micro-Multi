"""Regression checks for stalled streams, queued dispatch and settings wiring."""

import asyncio
from pathlib import Path

from masp.plugin_tools import get_dsh_settings, save_dsh_settings
from masp.storage import Store
from masp.supervisor import SupervisorManager


def test_dispatch_timeout_releases_capacity_and_reports_failure(tmp_path):
    async def run():
        manager = SupervisorManager(tmp_path, "timeout", max_concurrency=1)
        events = []
        manager.create_subagent(name="slow", role="test", description="test")

        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()

        async def emit(kind, data):
            events.append((kind, data))

        manager._execute_subagent_task = stalled
        result = await manager.execute_subagent_task(
            "slow",
            "test",
            cancel_event=asyncio.Event(),
            emit_event=emit,
            task_timeout_seconds=0.02,
        )
        assert result["status"] == "failed"
        assert "超时" in result["error"]
        assert manager.subagents["slow"].status == "failed"
        assert not manager.capacity.locked()
        assert not manager.agent_locks["slow"].locked()
        assert events[-1][0] == "subagent_progress"

    asyncio.run(run())


def test_cancel_interrupts_running_and_queued_workers(tmp_path):
    async def run():
        manager = SupervisorManager(tmp_path, "cancel", max_concurrency=1)
        cancelled = asyncio.Event()
        started = asyncio.Event()
        names = []

        async def stalled(name, *args, **kwargs):
            names.append(name)
            started.set()
            await asyncio.Event().wait()

        async def emit(*args):
            pass

        manager._execute_subagent_task = stalled
        tasks = [
            asyncio.create_task(
                manager.execute_subagent_task(
                    name,
                    "test",
                    cancel_event=cancelled,
                    emit_event=emit,
                )
            )
            for name in ("one", "two")
        ]
        await started.wait()
        cancelled.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert all(result["status"] == "cancelled" for result in results)
        assert names == ["one"]
        assert not manager.capacity.locked()

    asyncio.run(run())


def test_legacy_context_and_branch_settings(tmp_path: Path):
    store = Store(tmp_path / "test.sqlite")
    save_dsh_settings(
        store,
        {
            "context": {"maxContextTokens": 16000},
            "general": {"defaultBranch": "develop"},
            "agentLoop": {"recoveryMaxAttempts": 0},
        },
    )
    settings = get_dsh_settings(store)
    assert settings["context"]["maxContextTokens"] == 32000
    assert settings["workspace"]["defaultBranch"] == "develop"
    assert settings["agentLoop"]["recoveryMaxAttempts"] == 0


def test_zero_recovery_attempts_applies_to_worker(tmp_path):
    from types import SimpleNamespace

    class Response:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
            yield "data: [DONE]"

    class Client:
        requests = 0

        def stream(self, *args, **kwargs):
            self.requests += 1
            return Response()

    async def run():
        manager = SupervisorManager(tmp_path, "no-retry")
        client = Client()
        config = SimpleNamespace(
            model="mock",
            api_key="",
            base_url="http://mock/v1",
            temperature=0,
            max_output_tokens=4096,
        )

        async def emit(*args):
            pass

        result = await manager.execute_subagent_task(
            "worker",
            "test",
            client=client,
            default_config=config,
            load_model_config=lambda _: config,
            sub_tools=[],
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=4,
            recovery_max_attempts=0,
        )
        assert result["status"] == "failed"
        assert client.requests == 1

    asyncio.run(run())
