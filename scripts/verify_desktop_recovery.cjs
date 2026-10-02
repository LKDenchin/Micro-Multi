const { app, BrowserWindow, crashReporter } = require('electron');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const home=fs.mkdtempSync(path.join(os.tmpdir(),'masp-desktop-recovery-'));
process.env.MASP_HOME=home;
process.env.MASP_DESKTOP_TEST='1';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  const port=await new Promise(resolve=>{
    const server=net.createServer();server.listen(0,'127.0.0.1',()=>{
      const result=server.address().port;server.close(()=>resolve(result));
    });
  });
  process.env.MASP_PORT=String(port);
  require('../desktop/main.cjs');
  await app.whenReady();
  try {
    let win;
    for(let i=0;i<300;i++){
      win=BrowserWindow.getAllWindows()[0];
      if(win && win.webContents.getURL().startsWith('http') && !win.webContents.isLoading()) break;
      await sleep(100);
    }
    if(!win || !win.webContents.getURL().startsWith('http'))throw Error('desktop failed to start');
    const second=spawn(process.execPath,[path.resolve('.')],{env:{...process.env},windowsHide:true,stdio:'ignore'});
    const exitCode=await new Promise((resolve,reject)=>{second.on('exit',resolve);second.on('error',reject);});
    if(exitCode!==0 || BrowserWindow.getAllWindows().length!==1)throw Error('single-instance failed');
    const convId=await win.webContents.executeJavaScript(`(async()=>{
      const post=async(url,body)=>await (await fetch('/api/'+url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
      const conv=await post('conversations',{title:'Crash recovery chat'});
      await fetch('/api/dsh/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({general:{restoreLastSession:false}})});
      localStorage.setItem('masp.lastConversationId',conv.id);
      return conv.id;
    })()`);
    const oldWindow = win;
    const loaded=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('renderer failed to recover')),15000);
      app.once('browser-window-created', (_event,newWindow)=>{
        newWindow.webContents.once('did-finish-load',()=>{win=newWindow;clearTimeout(timer);resolve();});
      });
    });
    win.webContents.forcefullyCrashRenderer();
    await loaded;
    if(win===oldWindow)throw Error('crashed window was reused');
    if(crashReporter.getUploadToServer())throw Error('crash reports must remain local');
    let visible=false;
    for(let i=0;i<100;i++){
      visible=await win.webContents.executeJavaScript(`Boolean(document.querySelector('[data-id="${convId}"]')?.closest('.active'))`);
      if(visible)break;await sleep(100);
    }
    if(!visible)throw Error('saved conversation missing after renderer recovery');
    if(!win.webContents.getURL().includes('recover=renderer'))throw Error('recovery flag missing');
    const log=fs.readFileSync(path.join(home,'desktop.log'),'utf8');
    if(!log.includes('render-process-gone'))throw Error('crash diagnostic missing');
    const serverLog=fs.readFileSync(path.join(home,'server.stderr.log'),'utf8');
    const match=Array.from(serverLog.matchAll(/Started server process \[(\d+)\]/g)).pop();
    if(!match)throw Error('test backend pid not found');
    const backendLoaded=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('backend restart failed')),15000);
      win.webContents.once('did-finish-load',()=>{clearTimeout(timer);resolve();});
    });
    const python=path.resolve('.venv',process.platform==='win32'?'Scripts':'bin',process.platform==='win32'?'python.exe':'python');
    const seedCode="import sys;from pathlib import Path;from masp.storage import Store,now;s=Store(Path(sys.argv[1])/'store.sqlite3');s.put('message',{'id':'durable-desktop-partial','conversation_id':sys.argv[2],'role':'assistant','content':'durable desktop reply','created_at':now(),'execution_status':'running'},sys.argv[2]);s.update('conversation',sys.argv[2],execution_status='running',message_count=1)";
    const seed=spawn(python,['-c',seedCode,home,convId],{env:{...process.env,PYTHONPATH:path.resolve('src')},windowsHide:true,stdio:'ignore'});
    const seedExit=await new Promise((resolve,reject)=>{seed.on('exit',resolve);seed.on('error',reject);});
    if(seedExit!==0)throw Error('test checkpoint seed failed');
    process.kill(Number(match[1]));
    await backendLoaded;
    const response=await fetch(`http://127.0.0.1:${port}/api/health`);
    if(!response.ok)throw Error('restarted backend is not healthy');
    let interruptedVisible=false;
    for(let i=0;i<100;i++){
      interruptedVisible=await win.webContents.executeJavaScript("document.querySelector('#thread').textContent.includes('durable desktop reply') && document.querySelector('#thread').textContent.includes('上一轮连接已中断')");
      if(interruptedVisible)break;await sleep(100);
    }
    if(!interruptedVisible)throw Error('interrupted checkpoint did not restore in the UI');
    const dumpFiles=fs.readdirSync(path.join(home,'crashes'),{recursive:true}).filter(name=>String(name).endsWith('.dmp'));
    if(!dumpFiles.length)throw Error('local crash dump missing');
    const result={dumpCollected:true,restoreWithSettingOff:true,freshRenderer:true,localCrashReporter:true,singleInstance:true,rendererRecovered:true,backendRecovered:true,conversationRetained:true,partialReplyRestored:true,crashLogged:true};
    fs.mkdirSync(path.resolve('evidence/ui-regression'),{recursive:true});
    fs.writeFileSync(path.resolve('evidence/ui-regression/desktop-recovery.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
    app.quit();
  } catch(error){ console.error(error.stack); app.emit('before-quit');app.exit(1); }
})();
