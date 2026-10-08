from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "desktop_release", Path(__file__).resolve().parents[1] / "scripts/upload_desktop_release.py"
)
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def artifacts(tmp_path):
    root = tmp_path / "artifacts"
    for platform, names in (
        ("windows", ["Micro-Multi-Setup-0.1.0-x64.exe"]),
        ("linux", ["Micro-Multi-0.1.0-amd64.deb", "Micro-Multi-0.1.0-x86_64.AppImage"]),
    ):
        folder = root / platform
        folder.mkdir(parents=True)
        for name in names:
            (folder / name).write_bytes(name.encode())
        (folder / "SHA256SUMS.txt").write_text("platform-specific checksums")
    return root


def test_combined_checksums_cover_both_platforms(artifacts, tmp_path):
    assets = release.collect_assets(artifacts, tmp_path / "output", "0.1.0")
    assert len(assets) == 4
    assert assets[-1].read_text() == "".join(
        f"{release.digest(asset)}  {asset.name}\n" for asset in assets[:-1]
    )


@pytest.mark.parametrize("problem", ["missing", "duplicate", "empty"])
def test_incomplete_or_ambiguous_build_artifacts_abort(artifacts, tmp_path, problem):
    path = next(artifacts.rglob("*.exe"))
    if problem == "missing":
        path.unlink()
    elif problem == "empty":
        path.write_bytes(b"")
    else:
        (artifacts / path.name).write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="exactly one nonempty"):
        release.collect_assets(artifacts, tmp_path / "output", "0.1.0")


@pytest.mark.parametrize("existing", [False, True])
def test_create_or_reuse_draft_never_publishes(monkeypatch, artifacts, tmp_path, existing):
    assets = release.collect_assets(artifacts, tmp_path / "output", "0.1.0")
    draft = {"id": 17, "tag_name": "desktop-42", "draft": True, "html_url": "draft-url"}
    calls = []
    commands = []

    def api(endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload))
        if "releases?" in endpoint:
            return [draft] if existing else []
        if "/git/ref/" in endpoint:
            return {"object": {"type": "tag", "sha": "annotated"}}
        if "/git/tags/" in endpoint:
            return {"object": {"type": "commit", "sha": "source-commit"}}
        if payload:
            assert payload["draft"] is True
            assert payload["target_commitish"] == "source-commit"
            return draft
        return [
            {
                "name": p.name,
                "state": "uploaded",
                "size": p.stat().st_size,
                "digest": "sha256:" + release.digest(p),
            }
            for p in assets
        ]

    monkeypatch.setattr(release, "api", api)
    monkeypatch.setattr(release.subprocess, "run", lambda args, **kw: commands.append((args, kw)))
    assert release.upload_draft("owner/repo", "desktop-42", "source-commit", assets) == "draft-url"
    uploads = [args for args, _ in commands if args[1:3] == ["release", "upload"]]
    assert len(uploads) == 1
    assert all(str(path) in uploads[0] for path in assets)
    if existing:
        patch = next((args, kw) for args, kw in commands if "PATCH" in args)
        assert json.loads(patch[1]["input"]) == {"draft": True, "target_commitish": "source-commit"}
        assert not any(payload for _, payload in calls)
    else:
        assert any(payload and payload["draft"] for _, payload in calls)


@pytest.mark.parametrize("problem", ["published", "wrong_commit", "wrong_digest"])
def test_release_and_remote_asset_checks(monkeypatch, artifacts, tmp_path, problem):
    assets = release.collect_assets(artifacts, tmp_path / "output", "0.1.0")
    draft = {"id": 17, "tag_name": "desktop-42", "draft": problem != "published"}
    commands = []

    def api(endpoint, payload=None, **kwargs):
        if "releases?" in endpoint:
            return [draft]
        if "/git/ref/" in endpoint:
            return {
                "object": {
                    "type": "commit",
                    "sha": "different" if problem == "wrong_commit" else "source",
                }
            }
        return [
            {
                "name": p.name,
                "state": "uploaded",
                "size": p.stat().st_size,
                "digest": "sha256:wrong",
            }
            for p in assets
        ]

    monkeypatch.setattr(release, "api", api)
    monkeypatch.setattr(release.subprocess, "run", lambda args, **kw: commands.append(args))
    with pytest.raises(ValueError):
        release.upload_draft("owner/repo", "desktop-42", "source", assets)
    if problem != "wrong_digest":
        assert not commands, "Published releases and mismatched tags must be rejected before writes"
