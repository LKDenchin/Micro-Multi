/** Mount a plugin's client contributions inside Micro-Multi's own page. */
import React from 'react';
import {createPortal,PortalHost} from './plugin_portals.mjs';
import {Context} from '@deepseek-ai/cordis';
import Renderer from '@deepseek-ai/dsh-client-ui-renderer/client';
import ClientConnection from '@deepseek-ai/dsh-client-connection/client';
import TypertClient from '@deepseek-ai/dsh-typert-registry/client';
import GatewayClient from '@deepseek-ai/dsh-api-gateway/client';
import RemotesClient from '@deepseek-ai/dsh-api-remotes/client';
import SettingsClient from '@deepseek-ai/dsh-client-ui-settings/client';
import LocaleClient from '@deepseek-ai/dsh-client-locale/client';
import Timer from '@deepseek-ai/cordis-plugin-timer';
import * as plugin from 'micro-multi:plugin-client';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import {modules} from 'micro-multi:native-modules';
import dependencies,{nativeChildren,dependencyNames,packageName,clientSlots} from 'micro-multi:client-dependencies';

class Boundary extends React.Component {
 constructor(props){super(props);this.state={error:null};}
 static getDerivedStateFromError(error){return {error:error.message};}
 render(){return this.state.error?React.createElement('p',{role:'alert'},'插件页面加载失败：'+this.state.error):this.props.children;}
}
export async function mount(element,{rpcUrl,sessionId,mode='settings',targets={},model,modelOptions=false,settingsNamespaces=[]}){
 const ctx=new Context();let unmount;
 const portalHost=document.createElement('div');portalHost.className='plugin-body-portals plugin-slot-host';
 (mode==='settings'?element:targets['shell.overlay']??element).append(portalHost);

 const toolViews=new Map(),viewListeners=new Set();let viewRevision=0,viewId=0;const entryErrors=[];
 const updateViews=()=>{viewRevision++;for(const listener of viewListeners)listener();};
 try{
  await ctx.plugin(Renderer,{});
  await ctx.plugin(Timer,{});
  ctx.effect(()=>ctx.slots.onEntryError((slot,entry,error)=>{entryErrors.push(slot+': '+(error.message??String(error)));updateViews();}));
  let themeSnapshot,themeRevision=0;
  const updateTheme=()=>{const id=document.documentElement.dataset.theme||'light';themeSnapshot=Object.freeze({preference:id,fontSize:14,active:{id,colorScheme:id==='dark'?'dark':'light',tokens:{}},themes:[{id:'light',colorScheme:'light',tokens:{}},{id:'dark',colorScheme:'dark',tokens:{}}],revision:++themeRevision});ctx.emit('theme/change',themeSnapshot);};
  const theme={getTheme:()=>themeSnapshot,setTheme:value=>{if(!['light','dark','system'].includes(value))throw Error('Unknown theme: '+value);document.documentElement.dataset.theme=value==='system'?(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):value;}};
  updateTheme();
  ctx.reflect.provide('theme',theme);
  const themeObserver=new MutationObserver(updateTheme);
  themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','class']});ctx.effect(()=>()=>themeObserver.disconnect());
  const rpc={call:async(channel,method,payload,signal)=>{
   const response=await fetch(rpcUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel,method,payload}),signal});
   const value=await response.json();if(!response.ok)throw Error(value.detail??'插件接口调用失败');return value.result;
  },open:async function*(channel,method,payload,signal){
   // Persistent HTTP streams share Chromium's six connections with chat and
   // settings. WebSocket subscriptions do not consume that HTTP request pool.
   if(signal?.aborted)throw new DOMException('Subscription aborted','AbortError');
   const url=new URL(rpcUrl+'/socket',window.location.href);url.protocol=url.protocol==='https:'?'wss:':'ws:';
   const socket=new window.WebSocket(url);const packets=[];let wake,ended=false,error;
   const notify=()=>{wake?.();wake=undefined;};
   const abort=()=>{ended=true;socket.close();notify();};
   socket.onopen=()=>{socket.send(JSON.stringify({channel,method,payload}));};
   socket.onmessage=event=>{
    try{const packet=JSON.parse(event.data);if(packet.error){error=Error(packet.error.message);ended=true;socket.close();}
     else if(packets.length>=256){error=Error('Plugin subscription backlog exceeded');ended=true;socket.close();}
     else packets.push(packet.value);
    }catch(cause){error=cause;ended=true;socket.close();}notify();
   };
   socket.onerror=()=>{error=Error('插件订阅连接失败');ended=true;notify();};
   socket.onclose=event=>{ended=true;if(event.code!==1000&&!signal?.aborted&&!error)error=Error('插件订阅连接关闭：'+event.code);notify();};
   signal?.addEventListener('abort',abort,{once:true});
   try{while(!ended||packets.length){if(packets.length){yield packets.shift();continue;}await new Promise(resolve=>{wake=resolve;});}if(error)throw error;}
   finally{signal?.removeEventListener('abort',abort);socket.onopen=socket.onmessage=socket.onerror=socket.onclose=null;socket.close();}

  }};
  await ctx.plugin({name:'micro-multi-client-transport',apply:scope=>ClientConnection.installConnection(scope,{transport:{rpc},location:window.location})},{});
  for(const module of [TypertClient,GatewayClient,RemotesClient])await ctx.plugin(module,{});
  await ctx.plugin(SettingsClient,{});
  globalThis.__DSH_LOCALE__??={read:async()=>({languages:[document.documentElement.lang||'en'],preference:null}),onChange:()=>{}};
  const localeFiber=ctx.plugin(LocaleClient,{});
  await localeFiber;
  const isPluginSetting=entry=>entry.registrant!==localeFiber.name;
  // The previous settingsScope face maps onto the native form controller.
  ctx.reflect.provide('settingsScope',{bind:({namespace})=>ctx.configForms.get(namespace)});
  const registerSlot=ctx.slots.register;
  ctx.slots.register=function(options,component){
   if(!options.id&&options.key&&options.name!=='plugins.bundle.config'&&options.name!=='tool.call.toolview')options={...options,id:options.key,order:options.order??options.priority};
   return registerSlot.call(this,options,component);
  };
  if(!dependencyNames.includes('@deepseek-ai/dsh-api-session-controller')&&!ctx.get('sessions'))ctx.reflect.provide('sessions',{binding:id=>({session:{readAttachment:async attachmentId=>{const result=await rpc.call('/micro-multi','read-attachment',{sessionId:id,attachmentId});if(result.ok)result.value.data=Uint8Array.from(atob(result.value.data),char=>char.charCodeAt(0));return result;},},}),subagentAddress:()=>undefined});
  const directories=new Map();
  ctx.reflect.provide('modelDirectories',{directoryFor:id=>{
   if(directories.has(id))return directories.get(id);
   let snapshot={current:model?.()??{provider:'',model:''},groups:[],failures:[],status:'idle',pending:null,error:null},inflight;
   const listeners=new Set(),store={getSnapshot:()=>snapshot,subscribe:callback=>{listeners.add(callback);return ()=>listeners.delete(callback);}};
   const update=value=>{snapshot={...snapshot,...value};for(const listener of listeners)listener();};
   const directory={store,load:()=>inflight??=rpc.call('/micro-multi','model-directory',{sessionId:id,current:model?.()??{provider:'',model:''}}).then(value=>{update({...value,status:'ready'});return snapshot;}).catch(error=>{update({status:'error',error:error.message});throw error;}).finally(()=>{inflight=null;}),select:async selection=>{const value=await rpc.call('/micro-multi','model-directory',{sessionId:id,selection});update(value);return {ok:true};}};
   directories.set(id,directory);return directory;
  }});
  const binding={key:sessionId??undefined,ctx,hooks:{},keyedHooks:{},props:{sessionId:sessionId??undefined}},observable={getSnapshot:()=>binding,subscribe:()=>()=>{}};
  if(!dependencyNames.includes('@deepseek-ai/dsh-client-ui-session'))ctx.slots.installScope('session',{current:observable,bindingSource:()=>observable,renderArea:(binding,props)=>binding.key?props.children:props.empty?.()??null});
  const settingsSlots=['settings.section','settings.plugin.item','settings.plugin.page','settings.plugins.tab','settings.general.item','settings.action','plugins.bundle.config'];
  const children={...Object.fromEntries(settingsSlots.map(name=>[name,{kind:name==='plugins.bundle.config'?'keyed':'list',scope:'root'}])),'tool.call.toolview':{kind:'keyed',scope:'session'},'conversation.input.dock':{kind:'list',scope:'session'},'conversation.input.overlay':{kind:'list',scope:'session'},'conversation.input.activity':{kind:'single',scope:'session'},'conversation.input.plan':{kind:'single',scope:'session'},'conversation.input.permission':{kind:'single',scope:'session'},'conversation.input.model':{kind:'list',scope:'session'},'conversation.input.right':{kind:'list',scope:'session'},'conversation.input.left':{kind:'list',scope:'session'},'conversation.composer.dock':{kind:'list',scope:'session'},'conversation.header.actions':{kind:'list',scope:'session'},'conversation.session.header.actions':{kind:'list',scope:'session'},'conversation.session.header.utilities':{kind:'list',scope:'session'},'conversation.session.header.corner':{kind:'single',scope:'session'},'shell.overlay':{kind:'list',scope:'root'},'shell.bottom':{kind:'single',scope:'root'},'shell.leading':{kind:'single',scope:'root'}};
  const extraSlots=clientSlots.filter(name=>!children[name]);
  for(const name of extraSlots)children[name]={kind:'list',scope:name.startsWith('conversation.')?'session':'root'};
  function Surface(props){return React.createElement(PortalHost.Provider,{value:portalHost},React.createElement(SurfaceContent,props),mode==='settings'&&React.createElement('div',{className:'plugin-settings-portals',ref:node=>{if(node)node.append(portalHost);}}));}
  function ConfigField({form,node,path,value}){
   const [error,setError]=React.useState('');
   const save=async value=>{try{if(!await form.mutate([{op:'set',path,value}]))throw Error('设置保存失败，请检查参数');setError('');}catch(error){setError(error.message);}};
   const description=node.meta?.description;
   const label=(typeof description==='string'?description:description?.[ctx.locale.getLocale().active.startsWith('zh')?'zh':'en']??description?.en)??path.at(-1);
   if(node.type==='object')return React.createElement('fieldset',null,React.createElement('legend',null,label),...Object.entries(node.dict??{}).map(([key,child])=>React.createElement(ConfigField,{key,form,node:child,path:[...path,key],value:value?.[key]})));
   const secret=node.meta?.role==='secret';
   const common={disabled:!form.getSnapshot().writable,'aria-label':label};
   let input;
   if(node.type==='boolean')input=React.createElement('input',{...common,type:'checkbox',checked:!!value,onChange:event=>save(event.target.checked)});
   else if(['string','number'].includes(node.type))input=React.createElement('input',{...common,type:secret?'password':node.type==='number'?'number':'text',defaultValue:secret?'':value??'',key:JSON.stringify(value),onBlur:event=>{const next=node.type==='number'?Number(event.target.value):event.target.value;if(secret&&!next)return;if(next!==value)save(next);}});
   else input=React.createElement('textarea',{...common,defaultValue:JSON.stringify(value??null,null,2),key:JSON.stringify(value),onBlur:event=>{try{const next=JSON.parse(event.target.value);if(JSON.stringify(next)!==JSON.stringify(value))save(next);}catch{setError('请输入有效 JSON');}}});
   return React.createElement('label',{className:'extension-config-label'},label,input,error&&React.createElement('span',{role:'alert'},error));
  }
  function ConfigSection({descriptor}){
   const form=ctx.configForms.get(descriptor.ns);
   const state=React.useSyncExternalStore(callback=>form.subscribe(callback),()=>form.getSnapshot());
   const schema=ctx.settingsSchema.rehydrate(descriptor.schema);
   return React.createElement('section',{className:'plugin-client-section'},React.createElement('h3',null,descriptor.ns),React.createElement(ConfigField,{form,node:schema,path:[],value:state.value}));
  }
  function GenericSettings(){
   const mirror=ctx.configForms.describe();
   const snapshot=React.useSyncExternalStore(callback=>mirror.subscribe(callback),()=>mirror.getSnapshot());
   React.useEffect(()=>{mirror.ensure();},[]);
   const forms=(snapshot.view?.namespaces??[]).filter(row=>settingsNamespaces.includes(row.ns)&&row.autoGenerate!==false);
   return forms.length?React.createElement(React.Fragment,null,...forms.map(descriptor=>React.createElement(ConfigSection,{key:descriptor.ns,descriptor}))):React.createElement('p',null,snapshot.view?'此插件没有可调整参数。':'正在加载插件设置…');
  }
  function SurfaceContent(props){
   React.useSyncExternalStore(listener=>{viewListeners.add(listener);return ()=>viewListeners.delete(listener);},()=>viewRevision);
   for(const slot of settingsSlots)React.useSyncExternalStore(callback=>ctx.slots.subscribe(slot,callback),()=>ctx.slots.entries(slot));
   for(const slot of extraSlots)React.useSyncExternalStore(callback=>ctx.slots.subscribe(slot,callback),()=>ctx.slots.entries(slot));
   if(entryErrors.length)return React.createElement('p',{role:'alert'},'插件界面加载失败：'+entryErrors.join('；'));
   if(mode==='conversation')return React.createElement(Boundary,null,...Object.entries(targets).filter(([key,target])=>target&&children[key]&&!key.startsWith('settings.')&&key!=='plugins.bundle.config'&&(children[key].scope!=='session'||sessionId)).map(([key,target])=>createPortal(props.renderSlot(key,{}),target,key)),...extraSlots.filter(key=>key.startsWith('sidebar.')&&!targets[key]&&targets['shell.leading']).map(key=>createPortal(props.renderSlot(key,{wide:true}),targets['shell.leading'],key)),...[...toolViews].map(([target,view])=>createPortal(props.renderSlot('tool.call.toolview',view.props,{entryKey:view.props.toolName}),target,view.id)));
   if(ctx.slots.entries('plugins.bundle.config').some(entry=>entry.options.key===packageName))return React.createElement(Boundary,null,props.renderSlot('plugins.bundle.config',{view:'page'},{entryKey:packageName}));
   const slots=ctx.slots.entries('settings.plugin.page').length?['settings.plugin.page']:['settings.section','settings.plugin.item','settings.plugins.tab','settings.general.item','settings.action'];
   const present=slots.filter(slot=>ctx.slots.entries(slot).some(entry=>isPluginSetting(entry)));
   if(!present.length){const extra=extraSlots.filter(name=>ctx.slots.entries(name).length&&children[name].scope==='root');return React.createElement(Boundary,null,extra.length?extra.map(name=>React.createElement('section',{key:name},props.renderSlot(name,{wide:true}))):React.createElement(GenericSettings),props.renderSlot('shell.overlay',{}));}
   return React.createElement(Boundary,null,...present.map(slot=>React.createElement('section',{className:'plugin-client-section',key:slot},props.renderSlot(slot,{view:'page',close:()=>element.dispatchEvent(new CustomEvent('plugin-settings-close',{bubbles:true}))}))));
  }
  ctx.slots.register({name:'root',priority:-1000,children:Object.fromEntries(Object.entries(children).filter(([name])=>!nativeChildren.includes(name)))},Surface);
  if(mode==='conversation'&&sessionId&&modelOptions)ctx.slots.register({name:'conversation.input.model',id:'micro-multi-effort'},function Effort(){
   const directory=ctx.modelDirectories.directoryFor(sessionId);
   const state=React.useSyncExternalStore(directory.store.subscribe,directory.store.getSnapshot);
   React.useEffect(()=>{directory.load().catch(()=>{});const timer=setInterval(()=>directory.load().catch(()=>{}),10000);return ()=>clearInterval(timer);},[]);
   const selected=model?.()??state.current;
   const entry=state.groups.find(group=>group.id===selected?.provider)?.models.find(item=>item.id===selected?.model);
   const levels=entry?.reasoning?.efforts??[];
   if(!levels.length)return null;
   return React.createElement('select',{'aria-label':'推理强度',value:state.current?.reasoningEffort??entry.reasoning.defaultEffort??'',onChange:event=>directory.select({...selected,reasoningEffort:event.target.value||undefined}).catch(error=>console.error(error))},React.createElement('option',{value:''},'默认强度'),...levels.map(level=>React.createElement('option',{key:level.id,value:level.id},level.name||level.id)));
  });
  await ctx.plugin(Loader,{});const loader=ctx.loader;loader.internal=modules;
  ctx.reflect.provide('modules',modules);
  for(let index=0;index<dependencies.length;index++){modules.seed.set(dependencyNames[index],dependencies[index].default??dependencies[index]);await loader.create({id:'dependency-'+index,name:dependencyNames[index],config:{}});}
  modules.seed.set(packageName,plugin.default??plugin);
  const entryId=await loader.create({id:'selected-plugin',name:packageName,config:{}});
  await loader.await();const fiber=loader.resolve(entryId).fiber;
  if(!fiber)throw Error('插件客户端原生加载失败：'+packageName);
  for(const loaded of loader.entries())if(loaded.fiber)await loaded.fiber.await();
  for(const loaded of loader.entries())if(loaded.fiber&&loaded.fiber.state!==2)throw Error('插件客户端依赖缺少服务：'+loaded.options.name+' '+Object.keys(loaded.fiber.inject).filter(name=>!ctx.get(name)).join('、'));
  if(fiber.state!==2)throw Error('插件客户端缺少服务：'+Object.keys(fiber.inject).filter(name=>!ctx.get(name)).join('、'));
  element.replaceChildren();
  if(!portalHost.isConnected)(mode==='settings'?element:targets['shell.overlay']??element).append(portalHost);
  unmount=ctx.uiRenderer.mount(element);
  const observer=new MutationObserver(()=>{let changed=false;for(const target of toolViews.keys())if(!target.isConnected){toolViews.delete(target);changed=true;}if(changed)updateViews();});
  observer.observe(document.body,{childList:true,subtree:true});ctx.effect(()=>()=>observer.disconnect());
  const dispose=async()=>{unmount();toolViews.clear();await ctx.fiber.dispose();portalHost.remove();};
  dispose.renderToolView=(target,props)=>{if(!ctx.slots.entries('tool.call.toolview').some(entry=>entry.options.key===props.toolName))return false;toolViews.set(target,{id:toolViews.get(target)?.id??'tool-'+(++viewId),props});updateViews();return true;};
  return dispose;
 }catch(error){unmount?.();await ctx.fiber.dispose();portalHost.remove();throw error;}
}
