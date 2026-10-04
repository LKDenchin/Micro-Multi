"""A lockfile change or SDK rewrite must never promote plugin-modified code."""

import base64
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path


def test_framework_snapshot_uses_verified_archives_and_repairs_tampering(tmp_path):
    package = tmp_path / "node_modules" / "@deepseek-ai" / "cordis"
    (package / "lib").mkdir(parents=True)
    metadata = {
        "name": "@deepseek-ai/cordis",
        "version": "4.0.4",
        "type": "module",
        "main": "lib/index.js",
    }
    (package / "package.json").write_text(json.dumps(metadata))
    (package / "lib" / "index.js").write_text("export const value='plugin-modified';")
    archive = io.BytesIO()
    original = b"export const value='registry-original';"
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        entry = tarfile.TarInfo("package/lib/index.js")
        entry.size = len(original)
        tar.addfile(entry, io.BytesIO(original))
    research = tmp_path / ".research"
    research.mkdir()
    (research / "deepseek-ai-cordis-4.0.4.tgz").write_bytes(archive.getvalue())
    lock = {
        "packages": {
            "node_modules/@deepseek-ai/cordis": {
                "version": "4.0.4",
                "resolved": "https://registry.npmjs.org/unused-verified-fixture.tgz",
                "integrity": "sha512-"
                + base64.b64encode(hashlib.sha512(archive.getvalue()).digest()).decode(),
            }
        }
    }
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text(json.dumps(lock))
    guard = tmp_path / "framework_guard.mjs"
    shutil.copyfile(Path(__file__).parents[1] / "src/masp/native/framework_guard.mjs", guard)
    check = tmp_path / "check.mjs"
    check.write_text(
        "import {frameworkSource} from './framework_guard.mjs';console.log(frameworkSource("
        + json.dumps(str(package / "lib/index.js"))
        + "));"
    )

    def source():
        return subprocess.check_output([shutil.which("node"), str(check)], text=True).strip()

    assert source() == original.decode()
    cache = tmp_path / "node_modules/.micro-multi-framework"
    baseline = next(cache.iterdir())
    lock["unrelatedPlugin"] = "newly-installed"
    lock_path.write_text(json.dumps(lock))
    assert source() == original.decode()
    assert list(cache.iterdir()) == [baseline]
    (baseline / "cordis/lib/index.js").write_text("export const value='tampered-snapshot';")
    assert source() == original.decode()
