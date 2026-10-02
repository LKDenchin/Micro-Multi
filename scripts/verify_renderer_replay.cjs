const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const {execFileSync}=require('node:child_process');
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1500,height:950,webPreferences:{sandbox:true,backgroundThrottling:false}});
 const probe=path.resolve('src/masp/web/crash_replay_probe.js');
 fs.writeFileSync(probe,fs.readFileSync('src/masp/web/chat.js','utf8')+'\nwindow.replayMessage=renderMessage;window.replayTools=createOrUpdateToolGroup;');
 win.webContents.session.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8769/static/chat.js*']},(_d,cb)=>cb({redirectURL:'http://127.0.0.1:8769/static/crash_replay_probe.js'}));
 let crash=null;win.webContents.on('render-process-gone',(_e,d)=>{crash=d});
 try{
  await win.loadURL('http://127.0.0.1:8769/');await new Promise(r=>setTimeout(r,600));
  const python=path.resolve('.venv/Scripts/python.exe');
  const source="import sqlite3,json,sys;c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True);r=c.execute(\"select parent from records where kind='message' and id=?\",(sys.argv[2],)).fetchone();assert r;print(json.dumps([json.loads(x[0]) for x in c.execute(\"select data from records where kind='message' and parent=? order by rowid\",(r[0],))],ensure_ascii=False))";
  const rows=JSON.parse(execFileSync(python,['-X','utf8','-c',source,path.resolve('.masp/store.sqlite3').replaceAll('\\','/'),process.env.MASP_REPLAY_MESSAGE_ID||'msg-482aadf9afcd'],{encoding:'utf8',windowsHide:true}));
  await win.webContents.executeJavaScript('window.replayRows='+JSON.stringify(rows));
  const result=await win.webContents.executeJavaScript(`(async()=>{
   let peakNodes=0;
   for(let pass=0;pass<30;pass++){
    const thread=document.querySelector('#thread');thread.replaceChildren();
    document.body.classList.toggle('theme-light',pass%2===0);
    for(const m of window.replayRows){
     replayMessage(m.role,m.content,'',m.tool_events||[],{segments:m.segments,thinking:m.thinking,
      subagentEvents:m.subagent_events,messageId:m.id,executionStatus:m.execution_status});
    }
    for(const group of thread.querySelectorAll('.tool-activity-group'))group.open=true;
    for(const detail of thread.querySelectorAll('.tool-step-detail'))detail.hidden=false;
    thread.scrollTop=thread.scrollHeight;await new Promise(r=>setTimeout(r,25));
    thread.scrollTop=0;
    peakNodes=Math.max(peakNodes,thread.querySelectorAll('*').length);
   }
   return {passes:30,messages:window.replayRows.length,peakNodes,rendererAlive:true};
  })()`);
  if(crash)throw Error(JSON.stringify(crash));
  fs.writeFileSync('evidence/ui-regression/renderer-replay.json',JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));if(fs.existsSync(probe))fs.unlinkSync(probe);app.exit(0);
 }catch(e){console.error(e.stack);if(fs.existsSync(probe))fs.unlinkSync(probe);app.exit(1);}
 finally{if(fs.existsSync(probe))fs.unlinkSync(probe);}
});
