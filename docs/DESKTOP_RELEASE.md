# Desktop build and release

## Packages

| Platform | Package | Usage |
| --- | --- | --- |
| Windows x64 | `Micro-Multi-Setup-0.1.0-x64.exe` | NSIS installer, shortcuts and uninstaller |
| Linux x64 | `Micro-Multi-0.1.0-amd64.deb` | Install with `sudo apt install ./<package>.deb` |
| Linux x64 | `Micro-Multi-0.1.0-x86_64.AppImage` | Make executable and run; one portable file |

Packages include the Python backend, Node runtime, production dependencies and licenses. Git, Docker and external extension tools are not bundled. Data is stored in the user's application directory and is preserved during uninstall. The Windows installer is unsigned; updates are installed manually.

## Windows build

Use Windows x64, Python 3.14.7, Node.js 24+, npm and Git:

```powershell
npm ci
python scripts/prepare_desktop.py
npm exec electron-builder -- --win --x64 --publish never
python scripts/smoke_packaged_desktop.py
python scripts/release_checksums.py
```

`npm run desktop:dist` combines preparation and installer building.

## Linux build

Use an x64 Linux environment with Python 3.11+, Node.js 24+, npm and Git. Build on Linux or in a Linux VM/container; Windows npm dependencies must not be reused for Linux.

Install `binutils` for the Debian archive tool (`ar`). On Debian/Ubuntu: `sudo apt install binutils`. Desktop smoke checks additionally need the GUI libraries, D-Bus, GNOME Keyring, Xvfb and xauth installed by the Linux CI job.

```bash
npm ci
python3 scripts/prepare_desktop.py
npm exec electron-builder -- --linux deb AppImage --x64 --publish never
python3 scripts/release_checksums.py
```

`npm run desktop:dist:linux` combines preparation and both package targets. Linux preparation downloads a pinned CPython 3.14.8 standalone build, verifies its SHA-256, and installs dependencies from `requirements-desktop.lock`. Host Python is only the build bootstrap.

### Linux desktop checks

Model keys use a Secret Service keyring. A desktop environment with an unlocked GNOME Keyring or compatible service provides it. On a disposable Ubuntu build machine, the smoke check can run in its own D-Bus session:

```bash
dbus-run-session -- bash -c 'eval "$(printf "\n" | gnome-keyring-daemon --unlock --components=secrets)"; xvfb-run -a python3 scripts/smoke_packaged_desktop.py'
```

For unpacked Electron builds, configure the `chrome-sandbox` fallback helper before testing (`root:root`, mode `4755`). The Debian package configures sandboxing during installation, including an application-specific AppArmor profile on supported systems. The AppImage uses the platform's supported Chromium sandbox mechanism.

Install and check the actual `.deb`:

```bash
sudo apt install ./dist/desktop/Micro-Multi-0.1.0-amd64.deb
python3 scripts/smoke_packaged_desktop.py --app-dir /opt/Micro-Multi
sudo apt remove micro-multi
```

On headless machines, run the smoke command within the D-Bus/Xvfb session above. Extracting an AppImage with `--appimage-extract` also allows its shipped files to be checked with `--app-dir squashfs-root`. `--appimage-extract-and-run` runs without FUSE.

### Ubuntu AppImage sandbox policy

The AppImage launcher keeps Chromium sandboxing enabled. Ubuntu 24.04+ restricts unprivileged user namespaces through AppArmor. Install this application-specific policy once before launching the AppImage; the system-wide restriction stays enabled:

```bash
cat <<'EOF' | sudo tee /etc/apparmor.d/micro-multi-appimage >/dev/null
abi <abi/4.0>,
include <tunables/global>
profile micro-multi-appimage /tmp/{.mount_Micro-*,appimage_extracted_*}/micro-multi flags=(unconfined) {
  userns,
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/micro-multi-appimage
```

The same policy is provided in [`desktop/micro-multi-appimage.apparmor`](../desktop/micro-multi-appimage.apparmor). The paths cover default AppImage mounts and extract-and-run directories under `/tmp`; adapt them if using a different temporary directory. Debian installation configures its installed sandbox helper and namespace policy automatically.


## Runtime layout

```text
Micro-Multi.exe / micro-multi   Electron and embedded Node
resources/
  app/desktop/                 main process and sandboxed preload
  app/src/masp/                backend, UI and native extension hosts
  app/node_modules/            production JS dependencies and licenses
  python/                      relocatable Python and Python dependencies
  runtime-manifest.json        version, source URL and SHA-256 provenance
```

Real filesystem paths support Python, built-in MCP subprocesses, native hosts and the review CLI. An explicit source allowlist excludes user data, uploads, logs, evidence, tests, research and local configuration. Runtime dependencies are installed for the target OS.

Windows Python comes from python.org's embedded distribution. Linux Python uses a verified standalone CPython archive from release `20261001`; its source URL and archive hash are pinned in the build script and recorded in the runtime manifest. Exact production Python and npm dependencies are recorded in the lock files. Third-party licenses remain with shipped packages.

Installed data defaults to `%APPDATA%\Micro-Multi\data` on Windows and `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data` on Linux. `MASP_HOME` overrides either. Source mode retains the `.masp` default.

## Validation and publication

The website's download links are generated from the latest published GitHub Release, including its installer filenames and SHA256 checksum file. After publishing a release and uploading its files, rerun **Documentation site** in Actions to refresh both languages. No version or filename edits are needed. Drafts and prereleases are excluded. If a platform's installer or checksum file is missing, the page links to the latest release instead of an old or nonexistent file.

The smoke script starts the actual packaged executable with empty temporary data and no inherited model settings. It checks the required Node dependency and peer closure inside the package, backend health, built-in MCP, empty lists, the real renderer and desktop bridge, credential read/write/delete, review binary and native dsh Cordis. AppImage checks locate the running single file's actual extracted resources. A temporary loopback DevTools port and background-rendering test switches are enabled for this check only; test processes and data are cleaned afterward. See [release validation](RELEASE_VALIDATION.md).

Run `python scripts/publication_audit.py` before committing. Installation packages and `SHA256SUMS.txt` belong in Release assets, not source files.

In GitHub Actions, run **Desktop package build** to build and smoke-test Windows and Linux installers. Keep `upload_draft` unchecked to download the packages from the workflow artifacts. Check it to upload all three installers and one combined `SHA256SUMS.txt` to a Release draft after both builds pass.

Leave `draft_tag` blank to create `desktop-<run ID>`, or enter a tag for a new or existing draft. Reusing a draft replaces assets with the same names. Published releases are rejected; an existing Git tag must point to the build's commit. The workflow verifies uploaded file sizes and SHA-256 digests and adds the draft link to its summary. It does not publish the draft. Review the packages and release notes, then publish from GitHub Releases when ready.
