import json

import httpx
import pytest

from masp.agents import CompatibleProvider, ModelError
from masp.cli import main
from masp.lock import InstanceLock


def test_compatible_provider_structured_json_and_usage(monkeypatch):
    monkeypatch.setenv("MASP_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("MASP_MODEL_NAME", "local-coder")
    monkeypatch.setenv("MASP_MODEL_API_KEY", "secret-test-only")

    def response(url, **kwargs):
        assert url.endswith("/v1/chat/completions")
        assert kwargs["headers"]["Authorization"] == "Bearer secret-test-only"
        assert kwargs["json"]["model"] == "local-coder"
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [{"message": {"content": '{"findings": []}'}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            },
        )

    monkeypatch.setattr("masp.agents.httpx.post", response)
    result = CompatibleProvider().generate("reviewer", {}, {}, 1000)
    assert result.data == {"findings": []}
    assert result.input_tokens == 50 and result.output_tokens == 5


def test_provider_errors_do_not_echo_secret_response(monkeypatch):
    monkeypatch.setenv("MASP_MODEL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("MASP_MODEL_NAME", "local-coder")
    monkeypatch.setattr(
        "masp.agents.httpx.post",
        lambda url, **kwargs: httpx.Response(
            401, request=httpx.Request("POST", url), text="private-api-key"
        ),
    )
    with pytest.raises(ModelError) as raised:
        CompatibleProvider().generate("coder", {}, {}, 1000)
    assert "private-api-key" not in str(raised.value)


def test_cli_is_http_client(monkeypatch, capsys):
    called = []

    def request(method, url, **kwargs):
        called.append((method, url, kwargs["json"]))
        return httpx.Response(200, request=httpx.Request(method, url), json={"id": "project-test"})

    monkeypatch.setattr("masp.cli.httpx.request", request)
    assert main(["init", "CLI project"]) == 0
    assert called[0][1] == "http://127.0.0.1:3080/api/projects"
    assert called[0][2]["name"] == "CLI project"
    assert json.loads(capsys.readouterr().out)["id"] == "project-test"


def test_one_scheduler_per_data_directory(tmp_path):
    first = InstanceLock(tmp_path / "lock")
    try:
        with pytest.raises(ValueError, match="Another Micro-Multi"):
            InstanceLock(tmp_path / "lock")
    finally:
        first.close()
    second = InstanceLock(tmp_path / "lock")
    second.close()
