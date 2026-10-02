"""Write SHA256SUMS for generated installer assets."""

import hashlib
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "dist" / "desktop"
assets = sorted(
    [
        *root.glob("Micro-Multi-Setup-*.exe"),
        *root.glob("Micro-Multi-*.deb"),
        *root.glob("Micro-Multi-*.AppImage"),
    ]
)
if not assets:
    raise SystemExit("No installers found in dist/desktop")
lines = []
for asset in assets:
    with asset.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    lines.append(f"{digest}  {asset.name}")
(root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Checksums written for {len(assets)} installer(s)")
