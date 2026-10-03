/** The installed plugins' Fetch/RPC seam, without the DSH web shell. */
import {Service} from '@deepseek-ai/cordis';
import {OperatorPeer} from '@deepseek-ai/dsh-client-connection';

export default class PluginConnection extends Service {
 constructor(ctx){
  super(ctx,'connection');
  this.routes=new Map();this.handlers=new Map();this.interceptors=[];
  this.operator=new OperatorPeer(ctx);ctx.effect(()=>()=>this.operator.dispose());
 }
 get fetch(){const owner=this.ctx;return {register:route=>owner.effect(()=>{
   if(!route.path?.startsWith('/')||typeof route.fetch!=='function')throw Error('Invalid plugin route');
   if(this.routes.has(route.path))throw Error('Duplicate plugin route: '+route.path);
   this.routes.set(route.path,route);
   return ()=>{if(this.routes.get(route.path)===route)this.routes.delete(route.path);};
  })};}
 get rpc(){const owner=this.ctx;return {handle:(channel,handler)=>owner.effect(()=>{
   if(this.handlers.has(channel))throw Error('Duplicate plugin RPC channel');
   this.handlers.set(channel,handler);
   return ()=>{if(this.handlers.get(channel)===handler)this.handlers.delete(channel);};
  }),intercept:(channel,matches,handler)=>owner.effect(()=>{
   const entry={channel,matches,handler};this.interceptors.push(entry);
   return ()=>{this.interceptors=this.interceptors.filter(value=>value!==entry);};
  })};}
 createSharedFetchHandler(){return request=>this.handleFetch(request);}
 async handleFetch(request){
  const url=new URL(request.url),route=this.routes.get(url.pathname);
  if(route&&route.methods.includes(request.method))return route.fetch(request);
  if(request.method!=='POST')return new Response('Plugin route unavailable',{status:404});
  const envelope=await request.json(),slash=url.pathname.lastIndexOf('/');
  const channel=url.pathname.slice(0,slash),method=url.pathname.slice(slash+1);
  if(envelope.type!=='client-request'||envelope.method!==method)return new Response('Invalid RPC envelope',{status:400});
  const result=await this.dispatch(channel,method,envelope.payload,request.signal);
  return Response.json({type:'server-response',rpcId:envelope.rpcId,result});
 }
 async dispatch(channel,method,payload,signal){
  const matched=this.interceptors.filter(entry=>entry.channel===channel&&entry.matches(method));
  if(matched.length>1)throw Error('Multiple plugins own RPC endpoint: '+method);
  const handler=matched[0]?.handler??this.handlers.get(channel);
  if(!handler)throw Error('Plugin did not register RPC endpoint: '+channel+'/'+method);
  return await handler(method,payload,signal??new AbortController().signal,this.operator);
 }
 async call(channel,method,payload,signal){
  if(typeof channel!=='string'||typeof method!=='string'||!channel.startsWith('/')||/[?#\s]/.test(channel+method))throw Error('Invalid plugin RPC address');
  const rpcId=crypto.randomUUID(),route=this.routes.get(channel.replace(/\/$/,'')+'/'+method);
  if(route){
   if(!route.methods.includes('POST'))throw Error('Plugin route does not accept RPC');
   const response=await route.fetch(new Request('http://localhost'+route.path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId,method,payload}),signal}));
   if(!response.ok)throw Error('Plugin RPC HTTP '+response.status);
   const envelope=await response.json();
   if(envelope.type!=='server-response'||envelope.rpcId!==rpcId)throw Error('Invalid plugin RPC response');
   return envelope.result;
  }
  return await this.dispatch(channel,method,payload,signal);
 }
}
