import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildSync} from 'esbuild';
import {JSDOM} from 'jsdom';
const bundle=buildSync({entryPoints:['src/masp/web/chat.js'],bundle:true,format:'iife',write:false}).outputFiles[0].text;
for(const locale of ['zh-CN','en-US']){
 const dom=new JSDOM(readFileSync('src/masp/web/chat.html','utf8'),{url:'http://localhost:3080',runScripts:'outside-only',pretendToBeVisual:true});
 const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});
 w.fetch=async url=>{let data=[];if(String(url).includes('/dsh/settings'))data={general:{locale},theme:{mode:'light'}};if(String(url).includes('/dsh/plugins'))data={installed:[],official:[],mcp_servers:[],skills:[]};return new Response(JSON.stringify(data));};
 try{
  w.eval(bundle);
  await new Promise(resolve=>setTimeout(resolve,100));
  // Native client mount/cleanup effects must not take ownership of the host title.
  let titleMutations=0;
  const titleObserver=new w.MutationObserver(records=>{titleMutations+=records.length;});
  titleObserver.observe(w.document.head,{childList:true,subtree:true,characterData:true});
  w.document.title='DeepSeek Harness';
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.equal(w.document.title,'Micro-Multi');
  w.document.querySelector('title').textContent='Conversation — DeepSeek Harness';
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.equal(w.document.title,'Micro-Multi');
  const settledTitleMutations=titleMutations;
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.equal(titleMutations,settledTitleMutations);
  titleObserver.disconnect();
  const pluginSelect=w.document.createElement('select');pluginSelect.innerHTML='<option value="medium">默认强度</option>';
  w.document.querySelector('#plugin-model-options').append(pluginSelect);
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(pluginSelect.dataset.selectMenuId,undefined);
  assert.equal(pluginSelect.getAttribute('aria-hidden'),null);
  assert.equal(pluginSelect.options[0].textContent,'默认强度');
  pluginSelect.options[0].textContent='高强度';
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(pluginSelect.options[0].textContent,'高强度');
  assert.ok(w.document.querySelector('#chat-model-select').dataset.selectMenuId);
  // Repeated identical DOM notifications must settle and leave timers runnable.
  let mutations=0;const observer=new w.MutationObserver(records=>{mutations+=records.length;});
  observer.observe(w.document.body,{childList:true,subtree:true,attributes:true});
  w.document.querySelector('#chat-model-select').append(new w.Option('Long model name','model-fixture'));
  await new Promise(resolve=>setTimeout(resolve,100));const first=mutations;
  await new Promise(resolve=>setTimeout(resolve,100));assert.equal(mutations,first);observer.disconnect();
 }finally{dom.window.close();}
}
console.log('PASS: complete chat startup, live timers, stable DOM observers and native plugin control ownership in both locales; no simulated clicks');
