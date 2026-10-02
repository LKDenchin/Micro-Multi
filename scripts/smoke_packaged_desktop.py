"""Verify the actual packaged executable using an isolated, credential-free data home."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "desktop" / ("win-unpacked" if sys.platform == "win32" else "linux-unpacked")


def verify_node_dependencies(app_root: Path) -> int:
    """Resolve required dependency and peer edges strictly inside the shipped app."""
    package_root = (app_root / "resources" / "app").resolve()
    pending = [package_root / "package.json"]
    visited: set[Path] = set()
    while pending:
        manifest_path = pending.pop().resolve()
        if manifest_path in visited:
            continue
        assert manifest_path.is_relative_to(package_root), "Dependency escapes the packaged app"
        visited.add(manifest_path)
        manifest = json.loads(manifest_path.read_text("utf-8"))
        names = set(manifest.get("dependencies", {})) - set(
            manifest.get("optionalDependencies", {})
        )
        names.update(
            name
            for name in manifest.get("peerDependencies", {})
            if not manifest.get("peerDependenciesMeta", {}).get(name, {}).get("optional")
        )
        for name in names:
            directory = manifest_path.parent
            while directory.is_relative_to(package_root):
                candidate = directory / "node_modules" / name / "package.json"
                if candidate.is_file():
                    pending.append(candidate)
                    break
                if directory == package_root:
                    raise AssertionError(
                        f"Missing shipped dependency: {manifest.get('name')} → {name}"
                    )
                directory = directory.parent
    return len(visited) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=APP)
    parser.add_argument(
        "--appimage", type=Path, help="Launch an AppImage via its extract-and-run entry"
    )
    parser.add_argument("--startup-timeout", type=float, default=45)
    args = parser.parse_args()
    executable = args.app_dir.resolve() / (
        "Micro-Multi.exe" if sys.platform == "win32" else "micro-multi"
    )
    runtime_root = args.app_dir.resolve() / "resources" / "python"
    runtime = (
        runtime_root / "python.exe" if sys.platform == "win32" else runtime_root / "bin" / "python3"
    )
    if args.appimage:
        assert args.appimage.is_file(), "Build the AppImage first"
    else:
        assert executable.is_file() and runtime.is_file(), "Build the desktop app first"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        debug_port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="micro-multi-packaged-") as directory:
        home = Path(directory)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("MASP_", "MICRO_MULTI_", "PYTHON"))
            and key != "ELECTRON_RUN_AS_NODE"
        }
        env.update(
            MASP_HOME=directory,
            MASP_PORT=str(port),
            MASP_DESKTOP_TEST="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        startup = None
        if sys.platform == "win32":
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        launcher = [str(executable)]
        if args.appimage:
            launcher = [str(args.appimage.resolve()), "--appimage-extract-and-run"]
        process = subprocess.Popen(
            [
                *launcher,
                f"--remote-debugging-port={debug_port}",
                "--remote-debugging-address=127.0.0.1",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
            ],
            cwd=directory,
            env=env,
            startupinfo=startup,
            stdout=subprocess.DEVNULL if args.appimage else None,
            start_new_session=sys.platform != "win32",
        )
        checks: list[str] = []
        try:
            base = f"http://127.0.0.1:{port}"

            def get(route: str) -> object:
                with urllib.request.urlopen(base + route, timeout=2) as response:
                    return json.load(response)

            deadline = time.monotonic() + args.startup_timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged app exited: {process.returncode}")
                try:
                    health = get("/api/health")
                    break
                except (OSError, ValueError):
                    time.sleep(0.25)
            else:
                raise RuntimeError("Packaged backend did not become healthy")
            assert isinstance(health, dict) and health["builtin_mcp_ready"]
            checks.append("packaged backend and built-in MCP healthy")
            app_root = args.app_dir.resolve()
            if args.appimage:
                # Inspect the launched AppImage child, so probes use its actual
                # extracted resources rather than the build output directory.
                pending = [process.pid]
                while pending:
                    pid = pending.pop()
                    try:
                        child_exe = Path(f"/proc/{pid}/exe").resolve(strict=True)
                        if child_exe.name == "micro-multi":
                            app_root = child_exe.parent
                            break
                        children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
                        pending.extend(int(child) for child in children)
                    except (OSError, ValueError):
                        continue
                else:
                    raise RuntimeError("Could not locate the running AppImage resources")
                executable = app_root / "micro-multi"
                runtime = app_root / "resources" / "python" / "bin" / "python3"
            dependency_count = verify_node_dependencies(app_root)
            checks.append(
                f"{dependency_count} required Node dependencies and peers are self-contained"
            )
            assert (app_root / "resources" / "app" / "desktop" / "main.cjs").read_bytes() == (
                ROOT / "desktop" / "main.cjs"
            ).read_bytes(), "Packaged main process differs from the current source"
            checks.append("packaged main process matches current source")
            for route in ("projects", "conversations", "model-profiles"):
                assert get("/api/" + route) == [], f"Unexpected initial data: {route}"
            checks.append("no projects, conversations, or model profiles")
            with urllib.request.urlopen(base + "/", timeout=2) as response:
                assert b"chat.js" in response.read()
            checks.append("renderer page available")
            # Run outside the source checkout, without system Python/Node resolution.
            probe_env = {
                **env,
                "MICRO_MULTI_NODE": str(executable),
                "PYTHONPATH": str(app_root / "resources" / "app" / "src"),
            }
            result = subprocess.run(
                [
                    str(runtime),
                    "-c",
                    "import json,keyring,uuid; from masp.code_review import find_ocr_binary; "
                    "from masp.cordis_runtime import CordisWorker; from pathlib import Path; "
                    "print(type(keyring.get_keyring()).__name__); "
                    "account=uuid.uuid4().hex; "
                    "keyring.set_password('micro-multi-smoke',account,'temporary-test-value'); "
                    "assert keyring.get_password('micro-multi-smoke',account)=='temporary-test-value'; "
                    "keyring.delete_password('micro-multi-smoke',account); "
                    "assert find_ocr_binary().is_file(); "
                    "w=CordisWorker(Path('.'), {'root':str(Path('.').resolve()),'plugins':[]}, Path('.')); "
                    "assert w.inventory['versions']['cordis']=='4.0.4'; w.close(); "
                    "print('packaged Python, credential backend, review CLI and Cordis passed')",
                ],
                cwd=directory,
                env=probe_env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode:
                raise RuntimeError(result.stderr)
            checks.append(result.stdout.strip())
            javascript = r"""
            (async()=>{
              const pages=await (await fetch('http://127.0.0.1:DEBUG_PORT/json/list')).json();
              const page=pages.find(p=>p.type==='page'&&p.url.startsWith('http://127.0.0.1:APP_PORT'));
              if(!page)throw Error('Packaged renderer page missing');
              const ws=new WebSocket(page.webSocketDebuggerUrl);
              await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
              let id=0;const waiting=new Map();
              ws.onmessage=e=>{const p=JSON.parse(e.data);if(p.id&&waiting.has(p.id)){waiting.get(p.id)(p);waiting.delete(p.id);}};
              const send=(method,params={})=>new Promise(r=>{const n=++id;waiting.set(n,r);ws.send(JSON.stringify({id:n,method,params}));});
              let state;
              for(let i=0;i<100;i++){
                state=await send('Runtime.evaluate',{expression:'({ready:document.readyState,desktop:window.maspDesktop?.isDesktop,title:document.title})',returnByValue:true});
                if(state.result?.result?.value?.ready==='complete'&&state.result.result.value.desktop)break;
                await new Promise(r=>setTimeout(r,100));
              }
              ws.close();console.log(JSON.stringify({state:state.result.result.value}));process.exit(0);
            })().catch(e=>{console.error(e);process.exit(1);});
            """.replace("DEBUG_PORT", str(debug_port)).replace("APP_PORT", str(port))
            renderer = subprocess.run(
                [str(executable), "-e", javascript],
                cwd=directory,
                env={**env, "ELECTRON_RUN_AS_NODE": "1"},
                capture_output=True,
                text=True,
                timeout=90,
                startupinfo=startup,
            )
            if renderer.returncode:
                raise RuntimeError(renderer.stderr)
            captured = json.loads(renderer.stdout)
            assert captured["state"]["desktop"] and captured["state"]["ready"] == "complete"
            checks.append("packaged renderer and sandboxed desktop bridge loaded")
            # Chromium must have opened and loaded the actual desktop window.
            time.sleep(1)
            log = (home / "desktop.log").read_text("utf-8")
            assert '"desktop-start"' in log
            assert '"renderer-load-failed"' not in log
            checks.append("desktop startup without renderer load failure")
            print(json.dumps({"status": "passed", "checks": checks}, indent=2))
        except Exception:
            for diagnostic in home.rglob("*.log"):
                print(
                    f"{diagnostic.name}:\n{diagnostic.read_text('utf-8', errors='replace')[-12000:]}",
                    file=sys.stderr,
                )
            raise
        finally:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                except ProcessLookupError:
                    pass
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            time.sleep(1)


if __name__ == "__main__":
    main()
