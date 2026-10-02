import asyncio
import json
from types import SimpleNamespace

from masp.native_chat import native_chat_events
from masp.storage import Store


class Response:
    status_code = 200

    def __init__(self, delta, finish="stop"):
        self.delta = delta
        self.finish = finish

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aiter_lines(self):
        yield "data: " + json.dumps(
            {"choices": [{"delta": self.delta, "finish_reason": self.finish}]}
        )
        yield "data: [DONE]"


def test_official_loop_executes_bridge_tool_and_persists(tmp_path):
    class Client:
        def __init__(self):
            self.requests = []

        def stream(self, *args, **kwargs):
            self.requests.append(kwargs["json"])
            if len(self.requests) == 1:
                return Response(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-write",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"result.txt","content":"native"}',
                                },
                            }
                        ]
                    },
                    "tool_calls",
                )
            return Response({"content": "Created result.txt"})

    async def run():
        store = Store(tmp_path / "home" / "store.sqlite3")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        client = Client()
        cfg = SimpleNamespace(
            model="mock",
            api_key="",
            base_url="http://localhost",
            temperature=0.2,
            max_output_tokens=4096,
            timeout_seconds=10,
        )

        async def execute(name, arguments):
            args = json.loads(arguments)
            (workspace / args["path"]).write_text(args["content"])
            return "written"

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "write",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                    },
                },
            }
        ]
        events = [
            event
            async for event in native_chat_events(
                store,
                tmp_path / "home",
                workspace,
                "native-test",
                [
                    {"role": "system", "content": "Complete task"},
                    {"role": "user", "content": "Write result.txt"},
                ],
                tools,
                client,
                cfg,
                execute,
                asyncio.Event(),
                asyncio.Event(),
                max_steps=10,
                max_concurrency=2,
                remaining=lambda: 20,
            )
        ]
        assert (workspace / "result.txt").read_text() == "native"
        assert any(
            kind == "delta" and data["content"] == "Created result.txt" for kind, data in events
        )
        assert any(kind == "native-runtime" and data["eventCount"] > 0 for kind, data in events)
        assert list((tmp_path / "home" / "native-sessions").rglob("*.jsonl"))

    asyncio.run(run())


def test_native_children_run_concurrently_with_lead(tmp_path):
    async def run():
        store = Store(tmp_path / "home" / "store.sqlite3")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        entered = set()
        release = asyncio.Event()

        class Client:
            def stream(self, *args, **kwargs):
                payload = kwargs["json"]
                prompt = payload["messages"][-1]["content"]
                if "Current task:" not in prompt and prompt in {"child alpha", "child beta"}:
                    name = prompt.split()[-1]
                    entered.add(name)
                    if len(entered) == 2:
                        release.set()

                    class Delayed(Response):
                        async def aiter_lines(self):
                            await asyncio.wait_for(release.wait(), 5)
                            async for line in super().aiter_lines():
                                yield line

                    return Delayed({"content": name + " complete"})
                if prompt == "Start children":
                    return Response(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "spawn",
                                    "function": {
                                        "name": "start_subagents",
                                        "arguments": json.dumps(
                                            {
                                                "tasks": [
                                                    {
                                                        "subagent_name": name,
                                                        "prompt": "child " + name,
                                                    }
                                                    for name in ("alpha", "beta")
                                                ]
                                            }
                                        ),
                                    },
                                }
                            ]
                        },
                        "tool_calls",
                    )
                return Response({"content": "lead completed"})

        cfg = SimpleNamespace(
            model="mock",
            api_key="",
            base_url="http://localhost",
            temperature=0.2,
            max_output_tokens=4096,
            timeout_seconds=10,
        )

        async def execute(*args):
            return "done"

        from masp.supervisor import SUPERVISOR_TOOLS

        tools = [
            tool
            for tool in SUPERVISOR_TOOLS
            if tool["function"]["name"] in {"start_subagents", "wait_subagents"}
        ]
        events = [
            event
            async for event in native_chat_events(
                store,
                tmp_path / "home",
                workspace,
                "parallel-test",
                [
                    {"role": "system", "content": "Work"},
                    {"role": "user", "content": "Start children"},
                ],
                tools,
                Client(),
                cfg,
                execute,
                asyncio.Event(),
                asyncio.Event(),
                max_steps=20,
                max_concurrency=2,
                remaining=lambda: 20,
            )
        ]
        assert entered == {"alpha", "beta"}
        assert (
            sum(
                kind == "subagent_progress" and data["status"] == "completed"
                for kind, data in events
            )
            == 2
        )

    asyncio.run(run())
