const {app,BrowserWindow,clipboard,nativeImage} = require('electron');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const net=require('node:net');
const home=fs.mkdtempSync(path.join(os.tmpdir(),'micro-multi-clipboard-'));
process.env.MASP_HOME=home;process.env.MASP_DESKTOP_TEST='1';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});process.env.MASP_PORT=String(port);
 require('../desktop/main.cjs');await app.whenReady();
 try{
  let win;for(let i=0;i<200;i++){win=BrowserWindow.getAllWindows()[0];if(win&&win.webContents.getURL().startsWith('http')&&!win.webContents.isLoading())break;await sleep(100);}
  const a=path.join(home,'example.txt'),b=path.join(home,'example.bin');fs.writeFileSync(a,'clipboard text');fs.writeFileSync(b,Buffer.from([0,255,7]));
  clipboard.availableFormats=()=>['FileNameW'];clipboard.readBuffer=()=>Buffer.from(a+'\0'+b+'\0\0','utf16le');
  const files=await win.webContents.executeJavaScript('window.maspDesktop.readClipboardFiles()');
  if(files.length!==2||Buffer.from(files[0].data,'base64').toString()!=='clipboard text'||Buffer.from(files[1].data,'base64')[1]!==255)throw Error('native copied files lost bytes');
  clipboard.availableFormats=()=>['image/png'];clipboard.readImage=()=>nativeImage.createFromPath(path.resolve('docs/screenshots/permissions-popover-2026-09-29.png'));
  const image=await win.webContents.executeJavaScript('window.maspDesktop.readClipboardFiles()');if(image.length!==1||image[0].mime!=='image/png')throw Error('native image failed');
  const other=new BrowserWindow({show:false,webPreferences:{preload:path.resolve('desktop/preload.cjs'),contextIsolation:true,sandbox:true}});await other.loadURL('about:blank');const denied=await other.webContents.executeJavaScript('window.maspDesktop.readClipboardFiles()');if(denied.length)throw Error('untrusted frame read clipboard');other.close();
  console.log(JSON.stringify({nativeFiles:true,nativeImage:true,bytesPreserved:true,untrustedFrameBlocked:true,systemClipboardUntouched:true}));app.quit();
 }catch(e){console.error(e.stack);app.exit(1);}
})();
