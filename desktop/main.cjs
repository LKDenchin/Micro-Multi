const { app, BrowserWindow, dialog, ipcMain, Menu, shell, clipboard, crashReporter } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

app.setName('Micro-Multi');
if (process.platform === 'win32') app.setAppUserModelId('Micro-Multi');
const projectRoot = path.resolve(__dirname, '..');
const port = Number(process.env.MASP_PORT || 8765);
const appUrl = `http://127.0.0.1:${port}/`;
const EXPECTED_BUILD_ID = '2026-10-02-v17-parallel-collaboration';
let backend;
let ownsBackend = false;
let mainWindow;
let quitting = false;
let backendRestarts = 0;
let rendererCrashes = [];

const dataHome = path.resolve(process.env.MASP_HOME || (app.isPackaged
  ? path.join(app.getPath('userData'), 'data') : path.join(projectRoot, '.masp')));
fs.mkdirSync(dataHome, {recursive:true});
function logDesktop(event, detail) {
  try {fs.appendFileSync(path.join(dataHome,'desktop.log'), JSON.stringify({time:new Date().toISOString(),event,detail})+'\n');} catch {}
}
app.setPath('userData', path.join(dataHome, 'desktop-profile'));
if (process.platform === 'win32') app.disableHardwareAcceleration();
const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) app.quit();
if (singleInstance) {
  const crashDirectory = path.join(dataHome, 'crashes');
  fs.mkdirSync(crashDirectory, {recursive:true});
  app.setPath('crashDumps', crashDirectory);
  crashReporter.start({productName:'Micro-Multi', uploadToServer:false,
    globalExtra:{build:EXPECTED_BUILD_ID}});
  app.commandLine.appendSwitch('enable-logging', 'file');
  app.commandLine.appendSwitch('log-file', path.join(dataHome, 'chromium.log'));
  app.commandLine.appendSwitch('log-level', '1');
  logDesktop('desktop-start', {build:EXPECTED_BUILD_ID, versions:process.versions, crashDirectory});
}
app.on('second-instance', () => {
  if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); if (process.env.MASP_DESKTOP_TEST !== '1') { mainWindow.show(); mainWindow.focus(); } }
});
process.on('uncaughtException', error => logDesktop('uncaughtException',error.stack));
process.on('unhandledRejection', error => logDesktop('unhandledRejection',String(error)));
app.on('child-process-gone', (_event, detail) => logDesktop('child-process-gone',detail));

function pythonExecutable() {
  if (app.isPackaged) {
    const bundled = path.join(process.resourcesPath, 'python',
      ...(process.platform === 'win32' ? ['python.exe'] : ['bin', 'python3']));
    if (!fs.existsSync(bundled)) throw new Error('Bundled Python runtime is missing. Please reinstall Micro-Multi.');
    return bundled;
  }
  const candidates = process.platform === 'win32'
    ? [path.join(projectRoot, '.venv', 'Scripts', 'python.exe'), 'python']
    : [path.join(projectRoot, '.venv', 'bin', 'python'), 'python3', 'python'];
  return candidates.find((candidate) => candidate === 'python' || candidate === 'python3' || fs.existsSync(candidate));
}

async function checkServiceHealth() {
  try {
    const response = await fetch(`${appUrl}api/health`, { signal: AbortSignal.timeout(800) });
    if (!response.ok) return { running: false, upToDate: false };
    const data = await response.json();
    const upToDate = data && data.build_id === EXPECTED_BUILD_ID && data.builtin_mcp_ready === true;
    return { running: true, upToDate };
  } catch {
    return { running: false, upToDate: false };
  }
}


async function ensureBackend() {
  const initial = await checkServiceHealth();
  if (initial.running && initial.upToDate) return;
  if (initial.running && !initial.upToDate) {
    throw new Error('端口上已有其他版本的 Micro-Multi 服务。请先正常退出原服务后重开，避免中断运行中的对话。');
  }
  const executable = pythonExecutable();
  if (!executable) throw new Error('找不到 Python。请先在项目目录安装依赖：python -m pip install -e ".[dev]"');
  backend = spawn(executable, ['-m', 'masp.cli', 'serve', '--port', String(port)], {
    cwd: app.isPackaged ? dataHome : projectRoot,
    env: { ...process.env, MASP_HOME: dataHome, MICRO_MULTI_NODE: process.env.MICRO_MULTI_NODE || process.execPath, PYTHONPATH: path.join(projectRoot, 'src') },
    stdio: ['ignore', fs.openSync(path.join(dataHome,'server.stdout.log'),'a'), fs.openSync(path.join(dataHome,'server.stderr.log'),'a')],
    windowsHide: true,
  });
  ownsBackend = true;
  backend.on('error', error => logDesktop('backend-error',error.message));
  backend.on('exit', (code,signal) => {
    logDesktop('backend-exit',{code,signal});
    if (!quitting && mainWindow && !mainWindow.isDestroyed() && ++backendRestarts <= 3) {
      setTimeout(async () => {
        try {
          await ensureBackend();
          if (!quitting && mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.reload();
        } catch(error) { logDesktop('backend-restart-failed',error.message); }
      },700);
    }
  });
  const deadline = Date.now() + (process.platform === 'linux' ? 120000 : 30000);
  while (Date.now() < deadline) {
    if (backend.exitCode !== null) throw new Error(`Micro-Multi 服务提前退出，退出码 ${backend.exitCode}`);
    const status = await checkServiceHealth();
    if (status.running && status.upToDate) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('Micro-Multi 服务启动超时，请检查 Python 依赖和端口占用。');
}

function installApplicationMenu() {
  Menu.setApplicationMenu(null);
}

ipcMain.handle('masp:clipboard-files', async event => {
  if (event.senderFrame?.url !== appUrl && !event.senderFrame?.url?.startsWith(appUrl + '?')) return [];
  const formats = clipboard.availableFormats();
  const results = [];
  let total = 0;
  if (formats.includes('FileNameW')) {
    const names = clipboard.readBuffer('FileNameW').toString('utf16le').split('\0').filter(Boolean);
    for (const filePath of names.slice(0, 5)) {
      const stat = await fs.promises.stat(filePath).catch(() => null);
      if (!stat?.isFile() || stat.size > 10 * 1024 * 1024 || total + stat.size > 25 * 1024 * 1024) continue;
      const bytes = await fs.promises.readFile(filePath);
      total += bytes.length;
      const ext = path.extname(filePath).toLowerCase();
      const mime = {'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.txt':'text/plain','.md':'text/plain','.json':'application/json'}[ext] || 'application/octet-stream';
      results.push({name:path.basename(filePath),mime,data:bytes.toString('base64')});
    }
  } else {
    const image = clipboard.readImage();
    if (!image.isEmpty()) {
      const bytes = image.toPNG();
      if (bytes.length <= 10 * 1024 * 1024) results.push({name:'clipboard.png',mime:'image/png',data:bytes.toString('base64')});
    }
  }
  return results;
});

ipcMain.handle('masp:choose-project', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '打开本地 Git 项目', properties: ['openDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

async function createWindow(recovering = false) {
  if (!recovering) await ensureBackend();
  const previousWindow = mainWindow;
  const bounds = recovering && previousWindow && !previousWindow.isDestroyed()
    ? previousWindow.getBounds() : {width:1500,height:950};
  const window = new BrowserWindow({
    show: process.env.MASP_DESKTOP_TEST !== '1',
    ...bounds,
    minWidth: 1050,
    minHeight: 680,
    autoHideMenuBar: true,
    backgroundColor: '#171717',
    title: 'Micro-Multi',
    icon: path.join(projectRoot, 'src', 'masp', 'web', 'micro-multi.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = window;
  window.setMenuBarVisibility(false);
  window.webContents.on('render-process-gone', (_event, detail) => {
    logDesktop('render-process-gone', {...detail, build:EXPECTED_BUILD_ID,
      pid:window.webContents.getOSProcessId(), metrics:app.getAppMetrics()});
    if (quitting || window !== mainWindow || detail.reason === 'clean-exit') return;
    rendererCrashes = rendererCrashes.filter(time => Date.now() - time < 60000);
    rendererCrashes.push(Date.now());
    if (rendererCrashes.length > 3) {
      logDesktop('renderer-recovery-stopped', {reason:'repeated crashes within 60 seconds'});
      dialog.showErrorBox('Micro-Multi 界面恢复失败', '界面连续崩溃，已停止自动重试。已收到的对话仍保存在本地；请重启软件。诊断记录位于 .masp/crashes 和 .masp/chromium.log。');
      return;
    }
    setTimeout(async () => {
      if (quitting || window !== mainWindow || window.isDestroyed()) return;
      try {
        await createWindow(true);
        logDesktop('renderer-recovered', {strategy:'fresh-window'});
      } catch (error) {
        logDesktop('renderer-recovery-failed', {message:error.message});
      }
    }, 500);
  });
  const metricsTimer = setInterval(() => {
    if (!quitting && !window.isDestroyed()) logDesktop('desktop-metrics', {metrics:app.getAppMetrics()});
  }, 30000);
  metricsTimer.unref();
  window.on('closed', () => clearInterval(metricsTimer));
  window.on('unresponsive', () => logDesktop('window-unresponsive', {metrics:app.getAppMetrics()}));
  window.webContents.on('did-fail-load', (_event, code, description) => {
    logDesktop('renderer-load-failed', {code,description});
  });
  window.webContents.on('console-message', event => {
    if (event.level === 'error') logDesktop('renderer-console-error',
      {message:event.message.slice(0,2000), line:event.lineNumber, source:event.sourceId});
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  await window.loadURL(recovering ? appUrl + "?recover=renderer" : appUrl);
  if (recovering && previousWindow && !previousWindow.isDestroyed()) previousWindow.destroy();
}

app.whenReady().then(async () => {
  if (!singleInstance) return;
  installApplicationMenu();
  await createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
}).catch((error) => {
  void dialog.showErrorBox('Micro-Multi 无法启动', error.message);
  app.quit();
});

app.on('before-quit', () => {
  quitting = true;
  if (ownsBackend && backend && backend.exitCode === null) backend.kill();
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
