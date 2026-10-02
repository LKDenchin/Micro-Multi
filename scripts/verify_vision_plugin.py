"""Exercise the installed Vision Router through the real application host."""

import json
from pathlib import Path

from masp.cordis_runtime import NativeToolFailure, close_native_hosts
from masp.plugin_tools import execute_plugin
from masp.storage import Store

root = Path(__file__).resolve().parents[1]
store = Store(root / ".masp" / "store.sqlite3")
tools = {
    tool["name"]: tool
    for tool in store.list("plugin")
    if tool.get("bundle_id") == "bundle-dsh-vision-router"
}
image = str(root / "evidence" / "ui-regression" / "execution-memory-light.png")
try:
    try:
        description = json.loads(
            execute_plugin(
                tools["vision_describe"],
                json.dumps(
                    {"paths": [image], "question": "List the visible UI labels in this image."}
                ),
                root,
                store,
            )
        )
        cloud = {"status": "passed", "answer": description}
    except NativeToolFailure as error:
        code = error.contract.get("error", {}).get("code")
        if code not in {"VISION_RATE_LIMITED", "VISION_UNAVAILABLE"}:
            raise
        cloud = {"status": "provider_unavailable", "code": code, "error": error.contract["error"]}
    colors = json.loads(
        execute_plugin(tools["vision_colors"], json.dumps({"image": image, "top": 3}), root, store)
    )
    if isinstance(colors, str):
        colors = json.loads(colors)
    assert isinstance(colors, list) and colors and colors[0]["hex"].startswith("#")
    passed = 2 if cloud["status"] == "passed" else 1
    evidence = {
        "real_native_host": True,
        "vision_describe": cloud,
        "vision_colors": colors,
        "passed": passed,
    }
    (root / "evidence" / "ui-regression" / "vision-plugin-live.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"passed": passed, "real_native_host": True, "cloud_status": cloud["status"]}))
finally:
    close_native_hosts(store)
