const {app,BrowserWindow} = require('electron');
const fs=require('node:fs');const path=require('node:path');
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:256,height:256,transparent:true,frame:false,webPreferences:{offscreen:true}});
 try{
  const svg=fs.readFileSync('src/masp/web/micro-multi.svg','utf8');
  await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<html><body style="margin:0;width:256px;height:256px;background:transparent;display:grid;place-items:center">'+svg.replace('width="540" height="526"','width="256" height="249.36"')+'</body></html>'));
  await new Promise(r=>setTimeout(r,200));
  const png=(await win.webContents.capturePage({x:0,y:0,width:256,height:256})).toPNG();
  const root=path.resolve('src/masp/web');fs.writeFileSync(path.join(root,'micro-multi.png'),png);
  const header=Buffer.alloc(22);header.writeUInt16LE(1,2);header.writeUInt16LE(1,4);header.writeUInt16LE(1,10);header.writeUInt16LE(32,12);header.writeUInt32LE(png.length,14);header.writeUInt32LE(22,18);fs.writeFileSync(path.join(root,'micro-multi.ico'),Buffer.concat([header,png]));
  console.log('Generated 256px PNG and Windows ICO from the supplied SVG');app.exit(0);
 }catch(e){console.error(e);app.exit(1);}
});
