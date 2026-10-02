const {app,BrowserWindow}=require('electron');
const fs=require('node:fs');const path=require('node:path');
app.whenReady().then(async()=>{
 const probe=path.resolve('src/masp/web/chat_extension_probe.js');
 const source=fs.readFileSync('src/masp/web/chat.js','utf8');
 fs.writeFileSync(probe,source+`\nwindow.extensionProbe={renderPlugins:(value)=>{dshPluginInventory=value;renderDshPluginInventory();},send,openConversation,scheduleExtensionRefresh,setPaused:()=>{isChatExecutionPaused=true;updatePauseButtons(true);},setState:(items,id)=>{conversations=items;conversationId=id;draftProjectId=null;userExplicitlyUnboundProject=false;},get busy(){return busy;}};`);
 const win=new BrowserWindow({show:false,webPreferences:{sandbox:true}});
 win.webContents.session.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8769/static/chat.js*']},(_d,cb)=>cb({redirectURL:'http://127.0.0.1:8769/static/chat_extension_probe.js'}));
 try{
 await win.loadURL('http://127.0.0.1:8769/');
 const checks=await win.webContents.executeJavaScript(`(async()=>{
 await new Promise(r=>setTimeout(r,500));
 const checks=[];const assert=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 const fetchOriginal=window.fetch;let sent;
 const selector=document.querySelector('#project-select');selector.add(new Option('Other project','other-project'));selector.value='other-project';
 extensionProbe.setState([{id:'restored-unbound',project_id:null,message_count:2}], 'restored-unbound');
 window.fetch=(url,options)=>String(url).includes('/restored-unbound/messages')&&options?.method==='POST'?(sent=JSON.parse(options.body),Promise.resolve(new Response('data: {"delta":"continued"}\\n\\nevent: complete\\ndata: {}\\n\\n',{headers:{'Content-Type':'text/event-stream'}}))):fetchOriginal(url,options);
 extensionProbe.setPaused();
 await extensionProbe.send('继续');
 assert(!document.querySelector('#header-pause-chat')?.classList.contains('is-paused'),'New turn resets stale pause controls');
 assert(sent.project_id===null,'Restored unbound chat never switches to first project');
 assert(!extensionProbe.busy,'Unbound continuation completes and unlocks composer');
 extensionProbe.renderPlugins({official:[],installed:[{id:'bundle-ui-fold',name:'Fold fixture',enabled:true,components:[{type:'tool',name:'example'}]}],skills:[{name:'skill-a',scope:'installed',description:'A'}],mcp_servers:[]});
 const component=document.querySelector('#dsh-plugin-overview .plugin-component-details');
 assert(component && !component.open,'Plugin components are collapsed by default');
 component.open=true;await new Promise(r=>setTimeout(r,50));
 extensionProbe.renderPlugins({official:[],installed:[{id:'bundle-ui-fold',name:'Fold fixture',enabled:true,components:[{type:'tool',name:'example'}]}],skills:[],mcp_servers:[]});
 assert(document.querySelector('#dsh-plugin-overview .plugin-component-details').open,'Plugin expansion choice survives inventory refresh');
 const until=async(fn)=>{for(let i=0;i<100;i++){if(await fn())return;await new Promise(r=>setTimeout(r,50));}throw Error('Profile UI timed out');};
 document.querySelector('#native-profile-name').value='ui-profile';
 document.querySelector('#native-profile-config').value='[]';document.querySelector('#native-profile-patch').value='[]';
 document.querySelector('#native-profile-save').click();
 await until(async()=>(await(await fetchOriginal('/api/native-profiles')).json()).active==='ui-profile');
 assert(!document.querySelector('#native-profile-feedback').classList.contains('error'),'Native profile saves and activates through settings');
 await until(()=>!document.querySelector('#native-profile-save').disabled);
 document.querySelector('#native-profile-config').value='[ invalid yaml';document.querySelector('#native-profile-save').click();
 await until(()=>document.querySelector('#native-profile-feedback').classList.contains('error'));
 const profileState=await(await fetchOriginal('/api/native-profiles')).json();
 assert(profileState.active==='ui-profile'&&profileState.profiles.find(p=>p.name==='ui-profile').config==='[]','Invalid native profile preserves active configuration');
 await fetchOriginal('/api/dsh/plugins/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'native-profile-ui-profile',enabled:false})});
 window.fetch=()=>new Promise(()=>{});
 let returned=false;extensionProbe.scheduleExtensionRefresh();returned=true;
 assert(returned,'Extension inventory refresh does not block streaming reader');
 window.fetch=fetchOriginal;return checks;
 })()`);
 console.log(JSON.stringify({passed:checks.length,checks},null,2));fs.unlinkSync(probe);app.exit(0);
 }catch(err){console.error(err);fs.unlinkSync(probe);app.exit(1);}
});
