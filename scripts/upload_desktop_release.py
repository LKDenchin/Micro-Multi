"""Upload both verified desktop artifacts to an unpublished Release draft."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def api(endpoint: str, payload: dict | None = None, *, missing_ok: bool = False):
    command = ["gh", "api", endpoint]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
    )
    if result.returncode and missing_ok and "HTTP 404" in result.stderr:
        return None
    result.check_returncode()
    return json.loads(result.stdout)


def collect_assets(artifacts: Path, output: Path, version: str) -> list[Path]:
    names = (
        f"Micro-Multi-Setup-{version}-x64.exe",
        f"Micro-Multi-{version}-amd64.deb",
        f"Micro-Multi-{version}-x86_64.AppImage",
    )
    sources = []
    for name in names:
        matches = [path for path in artifacts.rglob(name) if path.is_file()]
        if len(matches) != 1 or matches[0].stat().st_size == 0:
            raise ValueError(f"Expected exactly one nonempty installer: {name}")
        sources.append(matches[0])
    output.mkdir(parents=True, exist_ok=True)
    assets = [Path(shutil.copy2(source, output / source.name)) for source in sources]
    checksum = output / "SHA256SUMS.txt"
    checksum.write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in assets), encoding="utf-8"
    )
    return [*assets, checksum]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def upload_draft(repo: str, tag: str, commit: str, assets: list[Path]) -> str:
    release = None
    page = 1
    while True:
        releases = api(f"repos/{repo}/releases?per_page=100&page={page}")
        release = next((item for item in releases if item["tag_name"] == tag), None)
        if release or len(releases) < 100:
            break
        page += 1
    if release and not release["draft"]:
        raise ValueError(f"Release {tag} is already published; choose a draft tag")

    # A pre-existing tag must describe the same source as these installers.
    ref = api(f"repos/{repo}/git/ref/tags/{quote(tag, safe='')}", missing_ok=True)
    if ref:
        obj = ref["object"]
        for _ in range(8):
            if obj["type"] == "commit":
                break
            obj = api(f"repos/{repo}/git/tags/{obj['sha']}")["object"]
        if obj["type"] != "commit" or obj["sha"] != commit:
            raise ValueError(f"Tag {tag} points to another commit; choose a new draft tag")

    if release:
        # PATCH, rather than an update through the CLI that could publish a draft.
        subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                f"repos/{repo}/releases/{release['id']}",
                "--input",
                "-",
            ],
            input=json.dumps({"draft": True, "target_commitish": commit}),
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        release = api(
            f"repos/{repo}/releases",
            {
                "tag_name": tag,
                "target_commitish": commit,
                "name": f"Micro-Multi · {tag}",
                "draft": True,
                "body": f"Verified Windows and Linux desktop packages.\n\nSource: {commit}",
            },
        )
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            "--clobber",
            "--repo",
            repo,
            "--",
            tag,
            *(str(path) for path in assets),
        ],
        check=True,
    )
    uploaded = api(f"repos/{repo}/releases/{release['id']}/assets?per_page=100")
    by_name = {asset["name"]: asset for asset in uploaded}
    for path in assets:
        asset = by_name.get(path.name, {})
        if (asset.get("state"), asset.get("size"), asset.get("digest")) != (
            "uploaded",
            path.stat().st_size,
            "sha256:" + digest(path),
        ):
            raise ValueError(f"Release asset verification failed: {path.name}")
    return release["html_url"]


def main() -> None:
    version = json.loads((ROOT / "package.json").read_text("utf-8"))["version"]
    assets = collect_assets(
        ROOT / "build/desktop-artifacts", ROOT / "build/release-assets", version
    )
    tag = os.environ.get("RELEASE_TAG", "").strip() or f"desktop-{os.environ['GITHUB_RUN_ID']}"
    url = upload_draft(os.environ["GH_REPO"], tag, os.environ["GITHUB_SHA"], assets)
    message = f"Release draft: {url}\n\nUploaded {len(assets) - 1} installers and combined SHA256SUMS.txt.\n"
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message)


if __name__ == "__main__":
    main()
