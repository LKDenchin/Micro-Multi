"""The OCR bridge passes the configured model and does not persist its key."""

import json
import subprocess

from masp.code_review import run_open_code_review
from masp.model_settings import ModelConfig


def test_ocr_bridge_maps_line_level_findings(tmp_path, monkeypatch):
    binary = tmp_path / "ocr"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("MASP_OCR_BINARY", str(binary))
    captured = {}

    def fake_run(command, *, cwd, env, **kwargs):
        captured.update(command=command, cwd=cwd, env=env)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "status": "success",
                    "summary": {"files_reviewed": 1},
                    "comments": [
                        {
                            "path": "app.py",
                            "start_line": 7,
                            "content": "Missing input check",
                            "severity": "high",
                            "existing_code": "return value",
                            "suggestion_code": "validate(value)",
                        }
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("masp.code_review.subprocess.run", fake_run)
    findings, report = run_open_code_review(
        tmp_path,
        ModelConfig("https://example.com/v1", "review-model", "private-key"),
    )
    assert captured["env"]["OCR_LLM_URL"] == "https://example.com/v1/chat/completions"
    assert captured["env"]["OCR_LLM_TOKEN"] == "private-key"
    assert captured["command"][1:4] == ["review", "--format", "json"]
    assert findings[0].blocking
    assert findings[0].line == 7
    assert report["comments"] == 1
    assert "private-key" not in repr(findings) + repr(report)
