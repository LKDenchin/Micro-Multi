"""Upload tested Linux installers to an existing draft and verify GitHub digests."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO = os.environ["GH_REPO"]
ROOT = Path(__file__).resolve().parents[1] / "dist" / "desktop"
NAMES = (
    "Micro-Multi-Setup-0.1.0-x64.exe",
    "Micro-Multi-0.1.0-amd64.deb",
    "Micro-Multi-0.1.0-x86_64.AppImage",
)


def api(endpoint: str):
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


release = api(f"repos/{REPO}/releases/tags/v0.1.0")
assert release["draft"], "Installer replacement requires a draft release"
expected = {}
for name in NAMES[1:]:
    path = ROOT / name
    with path.open("rb") as stream:
        expected[name] = (
            path.stat().st_size,
            "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest(),
        )
    subprocess.run(["gh", "release", "upload", "v0.1.0", str(path), "--clobber"], check=True)

assets = api(f"repos/{REPO}/releases/{release['id']}/assets?per_page=100")
by_name = {asset["name"]: asset for asset in assets}
for name in NAMES:
    asset = by_name[name]
    assert asset["state"] == "uploaded" and asset["digest"].startswith("sha256:")
    if name in expected:
        assert (asset["size"], asset["digest"]) == expected[name], name

checksums = ROOT / "SHA256SUMS.txt"
checksums.write_text(
    "".join(f"{by_name[name]['digest'].removeprefix('sha256:')}  {name}\n" for name in NAMES),
    encoding="utf-8",
)
subprocess.run(["gh", "release", "upload", "v0.1.0", str(checksums), "--clobber"], check=True)
assets = api(f"repos/{REPO}/releases/{release['id']}/assets?per_page=100")
checksum_asset = next(asset for asset in assets if asset["name"] == checksums.name)
assert checksum_asset["digest"] == "sha256:" + hashlib.sha256(checksums.read_bytes()).hexdigest()
print(json.dumps(assets, indent=2))
