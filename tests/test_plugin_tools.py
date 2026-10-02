"""Enabled JSON tools run as local plugins with validated input."""

import json
import sys

import pytest
from fastapi.testclient import TestClient

from masp.api import create_app
from masp.plugin_tools import discover_plugins, execute_plugin
from masp.storage import Store


def plugin_record(enabled=True):
    return {
        "id": "plugin-example",
        "name": "Echo",
        "description": "Return JSON input",
        "command": sys.executable,
        "args": ["-c", "import json,sys; print(json.dumps(json.load(sys.stdin)))"],
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "enabled": enabled,
    }


def test_plugin_discovery_and_execution(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    store.put("plugin", plugin_record(False))
    assert discover_plugins(store)[0] == []
    store.put("plugin", plugin_record())
    schemas, lookup = discover_plugins(store)
    alias = schemas[0]["function"]["name"]
    assert lookup[alias]["name"] == "Echo"
    result = execute_plugin(plugin_record(), '{"query":"hello"}', tmp_path)
    assert json.loads(result) == {"query": "hello"}
    with pytest.raises(ValueError, match="invalid"):
        execute_plugin(plugin_record(), '{"other":"hello"}', tmp_path)


def test_plugin_management_api(tmp_path):
    app = create_app(tmp_path / "home")
    with TestClient(app) as client:
        record = plugin_record(False)
        body = {key: value for key, value in record.items() if key != "id"}
        created = client.post("/api/plugins", json=body)
        assert created.status_code == 201
        plugin_id = created.json()["id"]
        assert not client.get("/api/plugins").json()[0]["enabled"]
        body["enabled"] = True
        assert client.put(f"/api/plugins/{plugin_id}", json=body).json()["enabled"]
        assert client.request("DELETE", f"/api/plugins/{plugin_id}", json={}).status_code == 204
