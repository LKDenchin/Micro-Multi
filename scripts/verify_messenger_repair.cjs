const { app, BrowserWindow } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  let child;
  const accounts = path.join(os.tmpdir(), `messenger-probe-${process.pid}.json`);
  try {
    const port = await new Promise(resolve => {
      const socket = net.createServer(); socket.listen(0, '127.0.0.1', () => {
        const port = socket.address().port; socket.close(() => resolve(port));
      });
    });
    if (!process.env.MICRO_MULTI_MESSENGER_FIXTURE) throw new Error('Set MICRO_MULTI_MESSENGER_FIXTURE to a disposable messenger fixture directory');
    child = spawn(process.env.MICRO_MULTI_NODE || 'node', ['server.js'], {
      cwd: path.resolve(process.env.MICRO_MULTI_MESSENGER_FIXTURE), windowsHide:true,
      env: {...process.env, PORT:String(port), HOST:'127.0.0.1', ACCOUNTS_FILE:accounts}
    });
    await new Promise((resolve,reject) => {
      const timeout = setTimeout(() => reject(new Error('Server startup timed out')), 10000);
      child.stdout.on('data', chunk => { if (String(chunk).includes('http://')) { clearTimeout(timeout); resolve(); } });
      child.once('error', reject); child.once('exit', code => { if(code) reject(new Error('Server exited '+code)); });
    });
    const window = new BrowserWindow({show:false, webPreferences:{sandbox:true}});
    const errors = [];
    window.webContents.on('console-message', (_event, level, message) => {
      if(level >= 3 && !message.includes('ERR_NAME_NOT_RESOLVED') && !message.includes('ERR_CERT')) errors.push(message);
    });
    await window.loadURL(`http://127.0.0.1:${port}`);
    const result = await window.webContents.executeJavaScript(`(async () => {
      const alerts = []; window.alert = text => alerts.push(text);
      const waitFor = async test => {
        const deadline = Date.now()+8000;
        while(!test()) { if(Date.now()>deadline) throw new Error('UI operation timed out: '+alerts.join(',')); await new Promise(resolve=>setTimeout(resolve,25)); }
      };
      document.getElementById('showRegister').click();
      document.getElementById('regUsername').value='probe-user';
      document.getElementById('regPassword').value='probe-password';
      document.getElementById('confirmPassword').value='probe-password';
      document.getElementById('registerBtn').click();
      await waitFor(()=>alerts.includes('注册成功'));
      document.getElementById('loginBtn').click();
      await waitFor(()=>document.getElementById('statusText').textContent==='已连接');
      document.getElementById('messageInput').value='probe message';
      document.getElementById('sendBtn').click();
      await waitFor(()=>document.getElementById('messagesContainer').textContent.includes('probe message'));
      const duplicate=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'probe-user',password:'probe-password'})});
      if(duplicate.status!==400) throw new Error('Duplicate account accepted');
      return {registered:true,connected:true,messageDelivered:true,duplicateRejected:true};
    })()`);
    if(errors.some(message=>/Uncaught|TypeError|ReferenceError/.test(message))) throw new Error(errors.join('\n'));
    fs.mkdirSync('evidence/ui-regression', {recursive:true});
    fs.writeFileSync('evidence/ui-regression/messenger-repair.json', JSON.stringify({passed:4,...result},null,2));
    child.kill(); fs.unlinkSync(accounts); app.exit(0);
  } catch(error) {
    console.error(error.stack); child?.kill(); if(fs.existsSync(accounts)) fs.unlinkSync(accounts); app.exit(1);
  }
});
