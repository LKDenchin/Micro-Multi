const {app,BrowserWindow}=require('electron');
const fs=require('node:fs');
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,webPreferences:{sandbox:true}});
 try{
  await win.loadURL('data:text/html,<div id="cards"></div>');
  const source=fs.readFileSync('src/masp/web/chat.js','utf8');
  const progressFunction=source.slice(source.indexOf('function createOrUpdateSubagentGroup('),source.indexOf('function collectTurnEditedFiles('));
  const functions=source.slice(source.indexOf('function agentCard('),source.indexOf('function buildMindmapSvg('));
  const result=await win.webContents.executeJavaScript(`(()=>{
   const profiles=[{id:'v4',name:'Old',model:'v4'},{id:'v3',name:'Main',model:'v3'}];
   const escapeHtml=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
   const icon=()=>'';
   const captureActivityView=()=>({});
   const updateActivityMarkup=(element,html)=>{element.innerHTML=html;};
   const restoreActivityView=()=>{};
   ${functions}
   ${progressFunction}
   const agent={id:'worker',name:'Worker',responsibility:'Work',model_profile_id:''};
   document.getElementById('cards').innerHTML=agentCard(agent)+modalAgentCard(agent,0);
   const inherited=[...document.querySelectorAll('select')];
   if(inherited.some(select=>select.value!==''||!select.selectedOptions[0].textContent.includes('跟随')))throw Error('Inherited model selected old first option');
   document.getElementById('cards').innerHTML=agentCard({...agent,model_profile_id:'v3'})+modalAgentCard({...agent,model_profile_id:'v4'},0);
   const explicit=[...document.querySelectorAll('select')].map(select=>select.value);
   if(explicit.join(',')!=='v3,v4')throw Error('Explicit binding lost');
   const progress=createOrUpdateSubagentGroup(null,[{agent_id:'worker',status:'running',effective_model:'v3'}]);
   if(!progress.querySelector('.subagent-runtime-model')?.textContent.includes('v3'))throw Error('Actual runtime model not displayed');
   return {inheritInBothEditors:true,explicitV3:true,explicitV4:true,actualRuntimeV3:true};
  })()`);
  fs.writeFileSync('evidence/ui-regression/subagent-model-selection.json',JSON.stringify({passed:4,...result},null,2));
  app.exit(0);
 }catch(error){console.error(error.stack);app.exit(1);}
});
