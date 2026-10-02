"""Manual real-provider regression; isolated project, existing OS-held credentials.

Run explicitly: .venv/Scripts/python scripts/replay_refraction.py
Never prints or persists model credentials. Not part of the offline test suite.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

import masp.api as api_module
from masp.model_settings import load_config
from masp.storage import Store


def main() -> None:
    original_home = Path(".masp").resolve()
    store = Store(original_home / "store.sqlite3")
    profile = next(p for p in store.list("model_profile") if p["model"] == "deepseek-flash")
    cfg = load_config(store, original_home, profile["id"])
    # All model calls in this isolated application use the existing configured provider.
    api_module.load_config = lambda *_a, **_kw: cfg
    evidence = Path("evidence/refraction-live").resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    app = api_module.create_app(evidence / "runtime")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "折射实验真实模型回归"}).json()
        conv = client.post("/api/conversations", json={"project_id": project["id"]}).json()
        print("Running exact user request through lead and real subagents", flush=True)
        response = client.post(
            f"/api/conversations/{conv['id']}/messages",
            json={
                "content": "制作一个物理实验演示，有关光的折射的",
                "access_mode": "commands",
            },
        )
        (evidence / "stream.txt").write_text(response.text, encoding="utf-8")
        messages = app.state.service.store.list("message", conv["id"])
        latest = next(m for m in messages if m["role"] == "assistant")
        team = app.state.service.store.get("conversation", conv["id"]).get("team") or {}
        root = Path(project["repository"])
        files = [
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts and ".masp" not in p.parts
        ]
        summary = {
            "model": cfg.model,
            "project_root": str(root),
            "files": files,
            "agent_names": [a["id"] for a in team.get("agents", [])],
            "termination_reason": latest.get("termination_reason"),
            "tools": [
                {"name": t.get("name"), "status": t.get("status")}
                for t in latest.get("tool_events", [])
            ],
            "model_steps": latest.get("model_steps"),
            "recovery": latest.get("model_recovery"),
            "final_response": latest["content"][-2500:],
        }
        (evidence / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {k: v for k, v in summary.items() if k != "final_response"}, ensure_ascii=False
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
