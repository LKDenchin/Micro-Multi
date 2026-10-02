"""Internal tool history must never become visible assistant speech."""

import pytest

from masp.compaction import ToolResultPruner, model_history
from masp.model_runtime import VisibleOutputFilter


@pytest.mark.parametrize("width", [1, 2, 7, 21, 80, 1000])
def test_memory_is_hidden_across_stream_boundaries(width):
    text = "开始\n<tool-execution-memory>secret source code</tool-execution-memory>\n完成"
    output = VisibleOutputFilter()
    visible = "".join(output.push(text[i : i + width]) for i in range(0, len(text), width))
    visible += output.push("", final=True)
    assert visible == "开始\n\n完成"


def test_unclosed_memory_is_hidden_but_normal_code_is_preserved():
    output = VisibleOutputFilter()
    assert (
        output.push("```js\nconst x = 1;\n```\n<tool-execution-memory>private", final=True)
        == "```js\nconst x = 1;\n```\n"
    )


def test_second_turn_history_keeps_execution_data_out_of_assistant_speech():
    messages = [
        {
            "role": "assistant",
            "content": "已完成修复",
            "tool_events": [
                {
                    "name": "read_file",
                    "path": "server.js",
                    "status": "completed",
                    "detail": "private source",
                }
            ],
        },
        {"role": "user", "content": "继续修复注册"},
    ]
    history = model_history(messages, ToolResultPruner())
    assistant = next(item for item in history if item["role"] == "assistant")
    assert assistant == {"role": "assistant", "content": "已完成修复"}
    assert "private source" in history[0]["content"]
    assert history[-1]["content"] == "继续修复注册"


def test_second_turn_api_suppresses_internal_memory_and_persists_clean_reply(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient
    from test_autonomous_collaboration import Response

    from masp.api import create_app

    monkeypatch.setattr("masp.model_settings.keyring.get_password", lambda *args: None)
    requests = []

    class FragmentedResponse(Response):
        async def aiter_lines(self):
            text = "结果<tool-execution-memory>private source code</tool-execution-memory>已说明"
            for char in text:
                yield "data: " + json.dumps({"choices": [{"delta": {"content": char}}]})
            yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}'
            yield "data: [DONE]"

    def stream(self, *args, **kwargs):
        requests.append(kwargs["json"])
        return FragmentedResponse()

    async def offline(*args, **kwargs):
        raise RuntimeError("offline title")

    monkeypatch.setattr("httpx.AsyncClient.stream", stream)
    monkeypatch.setattr("httpx.AsyncClient.post", offline)
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        profile = client.post(
            "/api/model-profiles",
            json={"name": "fixture", "model": "fixture", "base_url": "http://127.0.0.1:9999/v1"},
        ).json()
        conversation = client.post(
            "/api/conversations", json={"model_profile_id": profile["id"]}
        ).json()
        url = "/api/conversations/" + conversation["id"] + "/messages"
        for prompt in ["解释登录", "解释注册"]:
            response = client.post(url, json={"content": prompt, "main_only": True})
            assert response.status_code == 200
            assert "private source" not in response.text
            assert "tool-execution-memory" not in response.text
        assert len(requests) == 2
        previous_reply = next(
            message for message in requests[-1]["messages"] if message["role"] == "assistant"
        )
        assert previous_reply["content"] == "结果已说明"
