"""Concurrency, useful-output timeouts and durable asynchronous checkpoint regressions."""

import asyncio
import json
import time

import pytest
from test_autonomous_collaboration import Response, config

from masp.model_runtime import model_stream_lines
from masp.storage import Store
from masp.supervisor import SupervisorManager
from masp.turn_journal import TurnJournal


def test_keepalive_cannot_hide_stalled_model():
    async def run():
        closed = asyncio.Event()

        class Keepalive:
            async def aiter_lines(self):
                try:
                    while True:
                        await asyncio.sleep(0.005)
                        yield ": keepalive"
                finally:
                    closed.set()

        with pytest.raises(TimeoutError):
            async for _ in model_stream_lines(Keepalive(), 0.04, heartbeat_seconds=0.01):
                pass
        assert closed.is_set()

    asyncio.run(run())


def test_useful_tokens_reset_idle_and_heartbeat_does_not_duplicate_reads():
    async def run():
        heartbeats = []

        class Active:
            async def aiter_lines(self):
                for _ in range(6):
                    await asyncio.sleep(0.02)
                    yield "data:" + json.dumps({"choices": [{"delta": {"reasoning_content": "x"}}]})
                yield "data: [DONE]"

        async def heartbeat():
            heartbeats.append(time.monotonic())

        lines = [line async for line in model_stream_lines(Active(), 0.05, heartbeat, 0.005)]
        assert len(lines) == 7 and heartbeats

    asyncio.run(run())


def test_cancel_closes_pending_model_read():
    async def run():
        entered, closed = asyncio.Event(), asyncio.Event()

        class Blocked:
            async def aiter_lines(self):
                try:
                    entered.set()
                    await asyncio.Event().wait()
                    yield ""
                finally:
                    closed.set()

        async def consume():
            async for _ in model_stream_lines(Blocked(), 100):
                pass

        task = asyncio.create_task(consume())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()

    asyncio.run(run())


def test_slow_journal_keeps_event_loop_live_and_commits_before_return(tmp_path):
    async def run():
        store = Store(tmp_path / "db")
        store.put("conversation", {"id": "c"})
        journal = TurnJournal(store, "c", "m", "now", "mock")
        original = journal.save

        def slow_save():
            time.sleep(0.06)
            original()

        journal.save = slow_save
        task = asyncio.create_task(journal.consume_async('data: {"delta":"saved"}\n\n'))
        await asyncio.sleep(0.01)
        assert not task.done()
        await task
        assert journal.store.get("message", "m")["content"] == "saved"

    asyncio.run(run())


def test_cancelled_checkpoint_finishes_commit_before_close(tmp_path):
    async def run():
        store = Store(tmp_path / "db")
        store.put("conversation", {"id": "c"})
        journal = TurnJournal(store, "c", "m", "now", "mock")
        original = journal.save

        def slow_save():
            time.sleep(0.04)
            original()

        journal.save = slow_save
        task = asyncio.create_task(journal.consume_async('data: {"delta":"partial"}\n\n'))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await journal.close_async()
        saved = journal.store.get("message", "m")
        assert saved["content"] == "partial" and saved["execution_status"] == "interrupted"

    asyncio.run(run())


def test_worker_reference_budget_and_queued_state(tmp_path):
    async def run():
        requests, events = [], []
        queued = asyncio.Event()

        class Client:
            def stream(self, *args, **kwargs):
                requests.append(json.loads(json.dumps(kwargs["json"])))
                return Response({"content": "done"})

        async def emit(kind, data):
            events.append(data)
            if "槽位" in data.get("thinking", ""):
                queued.set()

        mgr = SupervisorManager(
            tmp_path,
            "c",
            max_concurrency=1,
            parent_context=[
                {"role": "user", "content": "original goal"},
                {"role": "tool", "content": "huge output" * 20000},
            ],
        )
        mgr.create_subagent("worker", "worker", "do task")
        await mgr.capacity.acquire()
        task = asyncio.create_task(
            mgr.execute_subagent_task(
                "worker",
                "current original task",
                client=Client(),
                default_config=config(),
                load_model_config=lambda _: config(),
                sub_tools=[],
                cancel_event=asyncio.Event(),
                pause_event=asyncio.Event(),
                emit_event=emit,
                max_turns=1,
                context_max_chars=12000,
            )
        )
        await asyncio.wait_for(queued.wait(), timeout=5)
        assert not requests and events and "槽位" in events[0]["thinking"]
        mgr.capacity.release()
        await task
        messages = requests[0]["messages"]
        assert messages[1]["content"].endswith("current original task\n")
        assert "original goal" in messages[2]["content"]
        assert len(messages[2]["content"]) < 3500

    asyncio.run(run())


def test_slow_profile_lookup_does_not_block_other_worker(tmp_path):
    async def run():
        import threading

        started = threading.Event()
        release = threading.Event()

        def load_profile(_):
            started.set()
            release.wait(2)
            return config()

        class Client:
            def stream(self, *args, **kwargs):
                return Response({"content": "done"})

        async def emit(*args):
            pass

        mgr = SupervisorManager(tmp_path, "c", max_concurrency=2)
        mgr.create_subagent("slow", "slow", "task").model_profile_id = "custom"
        mgr.create_subagent("fast", "fast", "task")
        kwargs = dict(
            client=Client(),
            default_config=config(),
            load_model_config=load_profile,
            sub_tools=[],
            cancel_event=asyncio.Event(),
            pause_event=asyncio.Event(),
            emit_event=emit,
            max_turns=1,
        )
        slow = asyncio.create_task(mgr.execute_subagent_task("slow", "task", **kwargs))
        try:
            await asyncio.wait_for(asyncio.to_thread(started.wait), 0.5)
            fast = await asyncio.wait_for(mgr.execute_subagent_task("fast", "task", **kwargs), 0.5)
            assert fast["status"] == "completed" and not slow.done()
        finally:
            release.set()
            await slow

    asyncio.run(run())
