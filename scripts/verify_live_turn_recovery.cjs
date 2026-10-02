const {app,BrowserWindow}=require('electron');
const http=require('node:http');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const net=require('node:net');
const home=fs.mkdtempSync(path.join(os.tmpdir(),'micro-multi-live-recovery-'));
process.env.MASP_HOME=home;process.env.MASP_DESKTOP_TEST='1';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async(fn,label)=>{for(let i=0;i<200;i++){if(await fn())return;await sleep(100);}throw Error(label);};
(async()=>{
 let streamResponse;let modelCalls=0;
 const model=http.createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{
  const input=JSON.parse(body||'{}');
  if(!input.stream){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({choices:[{message:{content:'Recovery test'}}]}));return;}
  modelCalls++;res.writeHead(200,{'Content-Type':'text/event-stream'});
  if(modelCalls===1){streamResponse=res;res.write('data: '+JSON.stringify({choices:[{delta:{content:'Working on recovery test. '}}]})+'\n\n');}
  else{res.end('data: '+JSON.stringify({choices:[{delta:{content:'Completed once [r1 write_file]'},finish_reason:'stop'}]})+'\n\ndata: [DONE]\n\n');}
 });});
 await new Promise(r=>model.listen(0,'127.0.0.1',r));
 const port=await new Promise(r=>{const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const p=server.address().port;server.close(()=>r(p));});});
 process.env.MASP_PORT=String(port);require('../desktop/main.cjs');await app.whenReady();
 try{
  let win;await wait(()=>{win=BrowserWindow.getAllWindows()[0];return win&&win.webContents.getURL().startsWith('http')&&!win.webContents.isLoading();},'Initial desktop failed');
  const conv=await win.webContents.executeJavaScript(`(async()=>{
   const post=async(u,b)=>await(await fetch('/api/'+u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})).json();
   const profile=await post('model-profiles',{name:'Recovery fixture',model:'fixture',base_url:'http://127.0.0.1:${model.address().port}/v1'});
   const conv=await post('conversations',{model_profile_id:profile.id});
   localStorage.setItem('masp.lastConversationId',conv.id);
   void fetch('/api/conversations/'+conv.id+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:'Create the recovery test file',access_mode:'commands',main_only:true,model_profile_id:profile.id})}).then(r=>r.text());
   return conv;
  })()`);
  await wait(()=>Boolean(streamResponse),'Model stream was not started');
  const old=win;
  const recovered=new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('Renderer did not recover')),15000);app.once('browser-window-created',(_e,next)=>next.webContents.once('did-finish-load',()=>{win=next;clearTimeout(timeout);resolve();}));});
  win.webContents.forcefullyCrashRenderer();await recovered;if(win===old)throw Error('Renderer was not recreated');
  await wait(()=>win.webContents.executeJavaScript(`fetch('/api/conversations/${conv.id}/live').then(r=>r.json()).then(v=>v.active)`),'Disconnected turn stopped');
  const call={index:0,id:'recovery-write',type:'function',function:{name:'write_file',arguments:JSON.stringify({path:'recovery-once.txt',content:'written once'})}};
  streamResponse.end('data: '+JSON.stringify({choices:[{delta:{tool_calls:[call]},finish_reason:'tool_calls'}]})+'\n\ndata: [DONE]\n\n');
  await wait(()=>win.webContents.executeJavaScript(`fetch('/api/conversations/${conv.id}/live').then(r=>r.json()).then(v=>!v.active&&v.message?.execution_status==='completed')`),'Background turn did not complete');
  await wait(()=>win.webContents.executeJavaScript("document.querySelector('#thread').textContent.includes('Completed once')"),'Recovered UI did not show completion');
  if(fs.readFileSync(path.join(home,'temporary',conv.id,'recovery-once.txt'),'utf8')!=='written once'||modelCalls!==2)throw Error('Tool/model execution was duplicated');
  console.log(JSON.stringify({rendererRecreated:true,turnSurvived:true,toolWrittenOnce:true,completionRestored:true,modelCalls}));
  model.close();app.exit(0);
 }catch(error){console.error(error);model.close();app.exit(1);}
})().catch(error=>{console.error(error);app.exit(1);});
