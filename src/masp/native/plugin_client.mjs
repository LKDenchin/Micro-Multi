/** Mount a plugin's client contributions inside Micro-Multi's own page. */
import React from 'react';
import {createPortal} from 'react-dom';
import {Context,Service} from '@deepseek-ai/cordis';
import Renderer from '@deepseek-ai/dsh-client-ui-renderer/client';
import ClientConnection from '@deepseek-ai/dsh-client-connection/client';
import TypertClient from '@deepseek-ai/dsh-typert-registry/client';
import GatewayClient from '@deepseek-ai/dsh-api-gateway/client';
import RemotesClient from '@deepseek-ai/dsh-api-remotes/client';
import * as plugin from 'micro-multi:plugin-client';
import dependencies from 'micro-multi:client-dependencies';

class Locale extends Service {
 constructor(ctx){super(ctx,'locale');this.dictionaries=new Map();this.language='zh';}
 register(name,dictionaries){this.dictionaries.set(name,dictionaries);return ()=>this.dictionaries.delete(name);}
 bind(name){return (key,values={})=>{
  const dictionaries=this.dictionaries.get(name)??{};
  let value=dictionaries[this.language]?.[key]??dictionaries.en?.[key]??key;
  if(typeof value==='function')return value(values);
  return String(value).replace(/\{(\w+)\}/g,(_,key)=>String(values[key]??'{'+key+'}'));
 };}
}
class Boundary extends React.Component {
 constructor(props){super(props);this.state={error:null};}
 static getDerivedStateFromError(error){return {error:error.message};}
 render(){return this.state.error?React.createElement('p',{role:'alert'},'插件页面加载失败：'+this.state.error):this.props.children;}
}
export async function mount(element,{rpcUrl,sessionId,mode='settings',targets={},model}){
 const ctx=new Context();let unmount;
 try{
  await ctx.plugin(Renderer,{});
  await ctx.plugin(Locale,{});
  const rpc={call:async(channel,method,payload,signal)=>{
   const response=await fetch(rpcUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel,method,payload}),signal});
   const value=await response.json();if(!response.ok)throw Error(value.detail??'插件接口调用失败');return value.result;
  },open:async function*(channel,method,payload,signal){
   const response=await fetch(rpcUrl+'/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel,method,payload}),signal});
   if(!response.ok)throw Error('插件流式接口 HTTP '+response.status);
   const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
   try{while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let end;while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);if(!line)continue;const packet=JSON.parse(line);if(packet.error)throw Error(packet.error.message);yield packet.value;}}}
   finally{await reader.cancel().catch(()=>{});}
  }};
  await ctx.plugin({name:'micro-multi-client-transport',apply:scope=>ClientConnection.installConnection(scope,{transport:{rpc},location:window.location})},{});
  for(const module of [TypertClient,GatewayClient,RemotesClient])await ctx.plugin(module,{});
  ctx.reflect.provide('modelDirectories',{directoryFor:()=>({load:async()=>({current:model?.()??null})})});
  const revision={revision:0};
  ctx.slots.installLocale({bind:name=>ctx.locale.bind(name),getSnapshot:()=>revision,subscribe:()=>()=>{}});
  const binding={key:sessionId??undefined,hooks:{},keyedHooks:{},props:{sessionId:sessionId??undefined}},observable={getSnapshot:()=>binding,subscribe:()=>()=>{}};
  ctx.slots.installScope('session',{current:observable,bindingSource:()=>observable,renderArea:(binding,props)=>binding.key?props.children:props.empty?.()??null});
  const children={'settings.section':{kind:'list',scope:'root'},'tool.call.toolview':{kind:'keyed',scope:'session'},'conversation.input.right':{kind:'list',scope:'session'},'conversation.input.left':{kind:'list',scope:'session'},'conversation.composer.dock':{kind:'list',scope:'session'},'conversation.header.actions':{kind:'list',scope:'session'},'shell.overlay':{kind:'list',scope:'root'}};
  function Surface(props){
   if(mode==='conversation')return React.createElement(Boundary,null,...Object.entries(targets).filter(([key])=>children[key]).map(([key,target])=>createPortal(props.renderSlot(key,{}),target,key)));
   return React.createElement(Boundary,null,...ctx.slots.entries('settings.section').map(entry=>React.createElement('section',{className:'plugin-client-section',key:entry.options.id},React.createElement('h3',null,typeof entry.options.label==='function'?entry.options.label():entry.options.label??entry.options.id),props.renderSlot('settings.section',{}, {only:entry.options.id}))));
  }
  ctx.slots.register({name:'root',children},Surface);
  for(const dependency of dependencies)await ctx.plugin(dependency.default??dependency,{});
  const fiber=ctx.plugin(plugin.default??plugin,{});await fiber;
  if(fiber.state!==2)throw Error('插件客户端缺少服务：'+Object.keys(fiber.inject).filter(name=>!ctx.get(name)).join('、'));
  const entries=ctx.slots.entries('settings.section');
  if(mode==='settings'&&!entries.length)throw Error('此插件尚未注册可显示的设置页面');
  element.replaceChildren();
  unmount=ctx.uiRenderer.mount(element);
  return ()=>{unmount();ctx.fiber.dispose();};
 }catch(error){unmount?.();await ctx.fiber.dispose();throw error;}
}
