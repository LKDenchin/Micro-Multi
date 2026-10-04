import assert from 'node:assert/strict';
import {mkdtemp,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import Schema from '@deepseek-ai/schemastery';
import {JSDOM} from 'jsdom';

// Render through the production Cordis/React adapter; no clicks or UI automation.
const root=await mkdtemp(join(tmpdir(),'micro-multi-client-test-'));
let dispose;const nodeProcess=globalThis.process;
const dom=new JSDOM('<!doctype html><html lang="zh-CN"><body><div id="root"></div></body></html>',{url:'http://localhost:3080',pretendToBeVisual:true});
for(const name of ['window','document','navigator','HTMLElement','Element','Node','MutationObserver','getComputedStyle'])Object.defineProperty(globalThis,name,{configurable:true,value:typeof dom.window[name]==='function'&&name==='getComputedStyle'?dom.window[name].bind(dom.window):dom.window[name]});
globalThis.requestAnimationFrame=dom.window.requestAnimationFrame.bind(dom.window);
globalThis.cancelAnimationFrame=dom.window.cancelAnimationFrame.bind(dom.window);
dom.window.WebSocket=class{send(){}close(){this.onclose?.({code:1000});}};
globalThis.fetch=async()=>new Response(JSON.stringify({detail:'No host in renderer unit test'}),{status:503});
try {
 await mkdir(join(root,'dsh'));
 await writeFile(join(root,'package.json'),JSON.stringify({name:'client-fixture',type:'module',exports:{'./client':'./dsh/client.js'},dsh:{client:{inject:['@deepseek-ai/dsh-client-runtime']}}}));
 await writeFile(join(root,'dsh/client.extra.js'),`window.__ModuleLoader__.load({id:'client-fixture',chunk:'client.extra.js',factory:()=>({value:'Native chunk ready'})});`);
 await writeFile(join(root,'dsh/client.js'),`window.__ModuleLoader__.load({id:'client-fixture',factory:require=>{
 const chunk=require.async('./client.extra.js');
 const React=require('react');const {createPortal}=require('react-dom');const primitives=require('@deepseek-ai/dsh-client-ui-primitives');if(!primitives.IconRefreshOutline16)throw Error('Legacy icon missing');return {inject:['slots','configForms','locale','theme','timer'],apply(ctx){
 ctx.effect(()=>{let active=true;chunk.then(({value})=>{if(active)ctx.slots.register({name:'settings.section',id:'native-chunk'},()=>React.createElement('p',null,value));});return ()=>{active=false;};});
 ctx.slots.inject('sidebar.footer.action',()=>ctx.slots.register({name:'sidebar.footer.action',id:'new-shell-entry'},()=>React.createElement('button',null,'New sidebar plugin')));
 ctx.slots.inject('settings.model.extra',()=>ctx.slots.register({name:'settings.model.extra',id:'new-setting'},()=>React.createElement('p',null,'Settings must stay in details')));
 if(!ctx.configForms)throw Error('Native settings forms missing');
 if(!ctx.theme.getTheme().active.colorScheme)throw Error('Native theme snapshot missing');
 ctx.slots.inject('conversation.input.right',()=>ctx.slots.register({name:'conversation.input.right',key:'legacy-widget',inject:id=>({session:id})},props=>React.createElement('p',null,'Widget session '+props.session)));
 ctx.slots.inject('shell.overlay',()=>ctx.slots.register({name:'shell.overlay',id:'overlay'},()=>React.createElement(React.Fragment,null,React.createElement('p',null,'Overlay ready'),createPortal(React.createElement('div',{'data-fixture-portal':'body',role:'dialog','aria-modal':true},React.createElement('button',null,'Plugin notice')),document.body))));
 ctx.slots.inject('tool.call.toolview',()=>ctx.slots.register({name:'tool.call.toolview',key:'fixture-tool'},props=>React.createElement('p',null,'Tool output '+props.block.content[0].text)));
 ctx.effect(()=>{const timer=setTimeout(()=>{
 ctx.slots.register({name:'settings.plugin.item',id:'fixture'},()=>React.createElement('p',null,'Native settings ready'));
 ctx.slots.register({name:'settings.general.item',id:'second'},()=>React.createElement('p',null,'Second settings ready'));
 },25);return ()=>clearTimeout(timer);});
 ctx.effect(()=>{const timer=setTimeout(()=>ctx.slots.register({name:'plugins.bundle.config',key:'client-fixture'},props=>React.createElement('p',null,'Dedicated settings '+props.view)),100);return ()=>clearTimeout(timer);});
 }};}});`);
 // Published bundles routinely minify the factory's require parameter.
 const {readFile}=await import('node:fs/promises');
 await writeFile(join(root,'dsh/client.js'),(await readFile(join(root,'dsh/client.js'),'utf8')).replaceAll('require','sdk'));
 const output=join(root,'output');
 execFileSync(nodeProcess.execPath,[resolve('src/masp/native/build_plugin_client.mjs'),root,output],{stdio:'pipe'});
 delete globalThis.process;
 const client=await import(pathToFileURL(join(output,'client.js')).href);
 dispose=await client.mount(document.querySelector('#root'),{rpcUrl:'/fixture/rpc',sessionId:'fixture'});
 assert.equal(document.documentElement.lang,'zh-CN');
 const deadline=Date.now()+2000;
 while(!document.body.textContent.includes('Native settings ready')&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,20));
 assert.match(document.body.textContent,/Native settings ready/);
 assert.match(document.body.textContent,/Native chunk ready/);
 assert.equal(document.body.textContent.split('Native settings ready').length-1,1);
 assert.equal(document.body.textContent.split('Second settings ready').length-1,1);
 while(!document.body.textContent.includes('Dedicated settings page')&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,20));
 assert.match(document.body.textContent,/Dedicated settings page/);
 assert.doesNotMatch(document.body.textContent,/Native settings ready/);
 assert.doesNotMatch(document.body.textContent,/加载失败|undefined/);
 await dispose();dispose=undefined;
 const target=document.createElement('div');document.body.append(target);
 dispose=await client.mount(document.querySelector('#root'),{rpcUrl:'/fixture/rpc',sessionId:'fixture',mode:'conversation',targets:{'conversation.input.right':target,'shell.overlay':target,'shell.leading':target,'settings.model.extra':target}});
 const widgetDeadline=Date.now()+2000;
 while(!target.textContent.includes('Widget session fixture')&&Date.now()<widgetDeadline)await new Promise(resolve=>setTimeout(resolve,20));
 assert.match(target.textContent,/Widget session fixture/);
 assert.match(target.textContent,/Overlay ready/);
 assert.match(target.textContent,/New sidebar plugin/);
 assert.doesNotMatch(document.body.textContent,/Settings must stay in details|Native settings ready|Dedicated settings page/);
 assert.ok(document.querySelector('[data-fixture-portal]').closest('.plugin-body-portals'));
 assert.notEqual(document.querySelector('[data-fixture-portal]').parentElement,document.body);
 const toolTarget=document.createElement('div');document.body.append(toolTarget);
 assert.equal(dispose.renderToolView(toolTarget,{toolName:'unknown-tool',block:{}}),false);
 assert.equal(dispose.renderToolView(toolTarget,{toolName:'fixture-tool',block:{content:[{type:'text',text:'ready'}]}}),true);
 const toolDeadline=Date.now()+2000;
 while(!toolTarget.textContent.includes('Tool output ready')&&Date.now()<toolDeadline)await new Promise(resolve=>setTimeout(resolve,20));
 assert.match(toolTarget.textContent,/Tool output ready/);
 await dispose();dispose=undefined;
 assert.equal(target.textContent,'');
 assert.equal(document.querySelector('[data-fixture-portal]'),null);
 dispose=await client.mount(document.querySelector('#root'),{rpcUrl:'/fixture/rpc',mode:'conversation',targets:{'conversation.input.right':target,'shell.overlay':target}});
 await new Promise(resolve=>setTimeout(resolve,150));
 assert.match(target.textContent,/Overlay ready/);
 assert.doesNotMatch(target.textContent,/strict session|加载失败|Widget session/);
 await dispose();dispose=undefined;
 // A plugin without its own settings page receives a schema-backed form.
 await writeFile(join(root,'dsh/client.js'),`window.__ModuleLoader__.load({id:'client-fixture',factory:sdk=>({apply(){}})});`);
 const genericOutput=join(root,'generic-output');
 execFileSync(nodeProcess.execPath,[resolve('src/masp/native/build_plugin_client.mjs'),root,genericOutput],{stdio:'pipe'});
 const schema=Schema.object({label:Schema.string().description('Plugin label'),enabled:Schema.boolean().description('Plugin enabled')}).toJSON();
 const descriptor={ns:'generic-config',schema,revision:0,applies:'live',value:{label:'Automatic form',enabled:true},base:{},user:{},secrets:[],autoGenerate:true};
 dom.window.WebSocket=class{constructor(){setTimeout(()=>this.onopen?.(),0);}send(){setTimeout(()=>this.onmessage?.({data:JSON.stringify({value:{clientId:'fixture'}})}),0);}close(){this.onclose?.({code:1000});}};
 globalThis.fetch=async(_url,options)=>{const body=JSON.parse(options.body);return new Response(JSON.stringify({result:{ok:true,value:body.method==='settings/describe'?{writable:true,hasDocument:true,namespaces:[descriptor]}:null}}),{headers:{'Content-Type':'application/json'}});};
 const generic=await import(pathToFileURL(join(genericOutput,'client.js')).href);
 document.documentElement.lang='en-US';
 dispose=await generic.mount(document.querySelector('#root'),{rpcUrl:'/fixture/rpc',settingsNamespaces:['generic-config']});
 assert.equal(document.documentElement.lang,'en');
 const formDeadline=Date.now()+2000;
 while(!document.querySelector('input[aria-label="Plugin label"]')&&Date.now()<formDeadline)await new Promise(resolve=>setTimeout(resolve,20));
 assert.equal(document.querySelector('input[aria-label="Plugin label"]')?.value,'Automatic form');
 assert.equal(document.querySelector('input[aria-label="Plugin enabled"]')?.checked,true);
 assert.equal(document.querySelector('[role="alert"]'),null);
 await dispose();dispose=undefined;
 console.log('PASS: legacy dsh/client.js, native settings dependency, asynchronous slots, keyed plugin page, unique React render');
} finally {
 globalThis.process=nodeProcess;await dispose?.();dom.window.close();
 assert.ok(root.startsWith(join(tmpdir(),'micro-multi-client-test-')));
 await rm(root,{recursive:true,force:true});
}
