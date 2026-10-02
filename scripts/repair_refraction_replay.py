"""Follow up the live replay with an independently observed rendering defect."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

import masp.api as api_module
from masp.model_settings import load_config
from masp.storage import Store

home = Path(".masp").resolve()
store = Store(home / "store.sqlite3")
profile = next(p for p in store.list("model_profile") if p["model"] == "deepseek-flash")
cfg = load_config(store, home, profile["id"])
api_module.load_config = lambda *_a, **_kw: cfg
evidence = Path("evidence/refraction-live").resolve()
app = api_module.create_app(evidence / "runtime")
with TestClient(app) as client:
    conv = app.state.service.store.list("conversation")[0]
    response = client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={
            "content": "实际浏览器验收发现 light-refraction.html 的折射光画错方向：左上入射时折射光向左下，切向传播方向不连续。请实际修复 refrSide 和关联角度弧线，并验证左右两种入射的几何方向、等折射率直线传播、全反射，不能仅检查角度数值。复杂验证代码先写脚本再执行。用中文简洁报告。",
            "access_mode": "commands",
        },
    )
    (evidence / "repair-stream.txt").write_text(response.text, encoding="utf-8")
    messages = app.state.service.store.list("message", conv["id"])
    latest = sorted(
        (m for m in messages if m["role"] == "assistant"), key=lambda m: m["created_at"]
    )[-1]
    (evidence / "repair-summary.json").write_text(
        json.dumps(
            {
                "content": latest["content"],
                "termination_reason": latest.get("termination_reason"),
                "tools": latest.get("tool_events"),
                "model_steps": latest.get("model_steps"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(latest["content"][-1800:])
