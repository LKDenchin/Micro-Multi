const { spawn } = require('node:child_process');
const { resolve } = require('node:path');
const fs = require('node:fs');
const net = require('node:net');
// Configured MCP entry point. Build/install dependencies separately; never run
// package-manager commands from a chat tool invocation.
const launchOnly = process.argv[2] === '--daemon-owner';
const [root, dataDir, portText = '7456'] = process.argv.slice(launchOnly ? 3 : 2);
const port = Number(portText);
if (!root || !dataDir || !Number.isInteger(port) || port < 1 || port > 65535) {
  process.stderr.write('Usage: node open_design_launcher.cjs <repository> <data-dir> [port]\n');
  process.exit(64);
}
const cli = resolve(root, 'apps/daemon/bin/od.mjs');
if (!fs.existsSync(cli) || !fs.existsSync(resolve(root, 'apps/daemon/dist/cli.js'))) {
  process.stderr.write('OpenDesign is not built. Install pinned pnpm dependencies and build @open-design/daemon first.\n');
  process.exit(78);
}
const listening = () => new Promise(resolve => {
  const socket = net.connect({ host: '127.0.0.1', port });
  socket.setTimeout(500);
  socket.once('connect', () => { socket.destroy(); resolve(true); });
  socket.once('error', () => { socket.destroy(); resolve(false); });
  socket.once('timeout', () => { socket.destroy(); resolve(false); });
});
(async () => {
  if (launchOnly || !await listening()) {
    if (launchOnly || process.platform !== 'win32') {
      fs.mkdirSync(dataDir, { recursive: true });
      const log = fs.openSync(resolve(dataDir, 'launcher.log'), 'a');
      const daemon = spawn(process.execPath, [cli, '--no-open', '--port', String(port)], {
        cwd: root, env: { ...process.env, OD_DATA_DIR: resolve(dataDir) },
        detached: true, windowsHide: true, stdio: ['ignore', log, log],
      });
      daemon.on('error', error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
      daemon.unref(); fs.closeSync(log);
      if (launchOnly) return;
    } else {
      // Use a separate launcher for the daemon's hidden startup. A containing
      // Windows Job may still own it; externally started daemons are reused.
      await new Promise((resolve, reject) => {
        const owner = spawn(process.execPath, [__filename, '--daemon-owner', root, dataDir, String(port)],
          { windowsHide: true, stdio: 'ignore' });
        owner.once('error', reject);
        owner.once('exit', code => code === 0 ? resolve() : reject(Error('Daemon launcher failed')));
      });
    }
    const deadline = Date.now() + 45000;
    while (!await listening()) {
      if (Date.now() > deadline) throw Error('OpenDesign daemon startup timed out; inspect launcher.log');
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  }
  const child = spawn(process.execPath, [cli, 'mcp', '--daemon-url', `http://127.0.0.1:${port}`], {
    cwd: root, env: { ...process.env, OD_DATA_DIR: resolve(dataDir) }, windowsHide: true, stdio: 'inherit',
  });
  child.on('error', error => { process.stderr.write(error.message + '\n'); process.exit(1); });
  child.on('exit', code => process.exit(code ?? 1));
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
})().catch(error => { process.stderr.write(error.message + '\n'); process.exit(1); });
