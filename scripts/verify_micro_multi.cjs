const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1500,height:950,webPreferences:{sandbox:true}});
 const probe=path.resolve('src/masp/web/chat_micro_probe.js');
 const names=['applyLocale','addAttachments','pendingAttachments','renderAttachments','openToolApprovalDialog','decideToolApproval','createOrUpdateSubagentGroup','dshSettings','loadPlugins','loadMcpServers','loadSkills','busy'];
 fs.writeFileSync(probe,fs.readFileSync('src/masp/web/chat.js','utf8')+'\n'+names.map(name=>`Object.defineProperty(window,'${name}',{get:()=>${name}});`).join('\n'));
 win.webContents.session.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8769/static/chat.js*']},(_d,cb)=>cb({redirectURL:'http://127.0.0.1:8769/static/chat_micro_probe.js'}));
 try {
 await win.loadURL('http://127.0.0.1:8769/');
 const result=await win.webContents.executeJavaScript(`(async()=>{
  const checks=[]; const assert=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
  for(let i=0;i<100&&!dshSettings?.id;i++)await new Promise(r=>setTimeout(r,50));
  assert(document.title.includes('Micro-Multi'),'product title renamed');
  assert(document.querySelector('#dsh-autonomous-hours').value==='8','8 hour default');
  const prose=document.createElement('div');prose.className='masp-markdown';prose.textContent='设置';document.querySelector('#thread').append(prose);
  applyLocale('en-US');await new Promise(r=>setTimeout(r,50));
  assert(document.querySelector('#settings-view h1').textContent==='Settings','English settings');
  assert(document.querySelector('#tool-approval-reject').textContent==='Reject this operation','English permission dialog');
  assert(document.querySelector('#dsh-autonomous-hours option:last-child').textContent==='8 hours','English autonomy choices');
  assert(prose.textContent==='设置','model prose preserved during locale switch');
  const walker=document.createTreeWalker(document.querySelector('#settings-view'),NodeFilter.SHOW_TEXT);const missing=[];while(walker.nextNode()){const n=walker.currentNode;if(/[\u4e00-\u9fff]/.test(n.nodeValue)&&!n.parentElement.closest('textarea,pre,code,.masp-markdown'))missing.push(n.nodeValue.trim());}assert(missing.length===0,'complete settings translation: '+missing.join(';'));
  await Promise.all([loadPlugins(),loadMcpServers(),loadSkills()]);await new Promise(r=>setTimeout(r,50));
  const allWalker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);const untranslated=[];while(allWalker.nextNode()){const n=allWalker.currentNode;if(/[\u4e00-\u9fff]/.test(n.nodeValue)&&!n.parentElement.closest('textarea,pre,code,.masp-markdown,.bubble,.conversation,.project-link span,#project-name,.attachment-chip,.tool-step-detail,.subagent-thinking-content,.subagent-error-detail'))untranslated.push(n.nodeValue.trim());}assert(untranslated.length===0,'complete interface translation: '+untranslated.join(';'));
  applyLocale('zh-CN');await new Promise(r=>setTimeout(r,20));assert(document.querySelector('#settings-view h1').textContent==='设置','Chinese restored');
  const dt=new DataTransfer();dt.items.add(new File([new Uint8Array([137,80,78,71])],'clipboard.png',{type:'image/png'}));
  document.querySelector('#prompt').dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:dt}));
  await new Promise(r=>setTimeout(r,100));assert(pendingAttachments.length===1&&pendingAttachments[0].data_url.startsWith('data:image/png'),'pasted image retained');assert(Boolean(document.querySelector('#attachment-list img')),'image preview visible');
  await addAttachments([new File(['PK binary'],'archive.zip',{type:'application/zip'}),new File(['hello'],'notes.txt',{type:'text/plain'})]);assert(pendingAttachments.length===3,'binary and text files accepted');assert(pendingAttachments[2].content==='hello','text contents read');
  const originalFetch=window.fetch;let sent=null;window.fetch=(url,options)=>{if(String(url).endsWith('/messages')&&options?.method==='POST'){sent=JSON.parse(options.body);return Promise.resolve(new Response('data: {"delta":"Attachment received"}\\n\\n'+'event: complete\\ndata: {}\\n\\n',{headers:{'Content-Type':'text/event-stream'}}));}return originalFetch(url,options);};
  document.querySelector('#prompt').value='';document.querySelector('#composer').requestSubmit();for(let i=0;i<100&&!sent;i++)await new Promise(r=>setTimeout(r,20));assert(sent?.attachments.length===3&&['请查看这些附件。','Please inspect the attachments.'].includes(sent.content),'attachment-only message sends');for(let i=0;i<100&&busy;i++)await new Promise(r=>setTimeout(r,20));window.fetch=originalFetch;
  const sub=createOrUpdateSubagentGroup(null,[{agent_id:'fail',status:'failed',thinking:'UnicodeEncodeError: gbk',error:'UnicodeEncodeError: gbk',steps:[]}]);assert(sub.querySelector('.subagent-error-detail').textContent.includes('gbk'),'failure reason visible');
  openToolApprovalDialog({approval_id:'test',conversation_id:'conv',tool:'run_command',arguments:'{}',required_mode:'commands',reason:'Confirm'});assert(document.querySelector('#tool-approval-dialog').open,'real approval dialog opens');assert(document.querySelector('#tool-approval-allow-files').hidden,'file approval cannot grant a command');document.querySelector('#tool-approval-dialog').close();
  return checks;
 })()`);
 const evidence=path.resolve('evidence/ui-regression/micro-multi-checks.json');fs.mkdirSync(path.dirname(evidence),{recursive:true});fs.writeFileSync(evidence,JSON.stringify(result,null,2));
 console.log(JSON.stringify({passed:result.length,checks:result},null,2));fs.unlinkSync(probe);app.exit(0);
 }catch(e){console.error(e.stack);fs.unlinkSync(probe);app.exit(1);}
});
