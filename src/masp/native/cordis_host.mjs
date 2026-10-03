/** Isolated native Cordis host. Protocol is private to Micro-Multi's backend. */
import {AsyncLocalStorage} from 'node:async_hooks';
import {randomUUID,createHash} from 'node:crypto';
import { Context, Service } from '@deepseek-ai/cordis';
import { ToolRuntime } from '@deepseek-ai/dsh-tools';
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt';
import {boot,loadOverlayPatches,loadOptionalPatches,loadProfileDirectory,loadEnv,generateConfigSchema,renderConfigDump} from '@deepseek-ai/dsh-app-boot';
import {entryListSchema,applyEntryPatches} from '@deepseek-ai/cordis-plugin-include';
import yaml from 'js-yaml';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import SessionStore from '@deepseek-ai/dsh-session';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import LlmRuntime from '@deepseek-ai/dsh-llm';
import SkillRegistry from '@deepseek-ai/dsh-skill';
import ApprovalService from '@deepseek-ai/dsh-user-approval';
import * as SpawnInProcess from '@deepseek-ai/dsh-subagent-spawn-in-process';
import * as ForkInProcess from '@deepseek-ai/dsh-subagent-fork-in-process';
import SubagentRuntime from '@deepseek-ai/dsh-subagent';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl';
import * as SkillFilesystem from '@deepseek-ai/dsh-skill-filesystem';
import LocalFileSystem from '@deepseek-ai/dsh-fs-local';
import LocalAttachmentStore from '@deepseek-ai/dsh-attachment-local';
import { registerHooks, createRequire } from 'node:module';
import { readdirSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import { format } from 'node:util';
import {runNativeChat,receiveBridge} from './chat_runtime.mjs';
import PluginConnection from './plugin_connection.mjs';
import TypertRegistry from '@deepseek-ai/dsh-typert-registry';
import TypertGateway from '@deepseek-ai/dsh-api-gateway';
import * as ApiRemotes from '@deepseek-ai/dsh-api-remotes';
const protocolWrite = process.stdout.write.bind(process.stdout);
const PREFIX = 'MICRO_MULTI_CORDIS:';
const write = value => {
  const encoded=JSON.stringify(value);
  if (Buffer.byteLength(encoded)>500000) throw Error('Cordis response exceeds 500 KB');
  protocolWrite(PREFIX+encoded+'\n');
};
// Console output cannot corrupt JSON RPC. Diagnostics remain in the backend-owned log.
for (const name of ['log','info','warn','error','debug']) console[name]=(...args)=>process.stderr.write(format(...args).slice(0,8000)+'\n');
const runtimeRequire=createRequire(import.meta.url);
const available=new Map();
const packageRoots=new Map();
const scopeDir=dirname(dirname(runtimeRequire.resolve('@deepseek-ai/cordis/package.json')));
for(const name of readdirSync(scopeDir)){
 try{available.set('@deepseek-ai/'+name,pathToFileURL(runtimeRequire.resolve('@deepseek-ai/'+name)).href);}catch{}
}
available.set('cordis',available.get('@deepseek-ai/cordis'));
registerHooks({resolve(specifier,context,nextResolve){
  // Explicit URLs work for both ESM import and CJS require. Resolve them before
  // installing hooks to avoid recursion and force the shared framework instance.
  if (['@deepseek-ai/cordis','cordis','@deepseek-ai/dsh-tools'].includes(specifier))
    return {url:available.get(specifier),shortCircuit:true};
  if(packageRoots.has(specifier))return {url:packageRoots.get(specifier),shortCircuit:true};
  try{return nextResolve(specifier,context);}catch(error){
    if(available.has(specifier))return {url:available.get(specifier),shortCircuit:true};
    try{return {url:pathToFileURL(runtimeRequire.resolve(specifier)).href,shortCircuit:true};}catch{}
    throw error;
  }
}});
class WorkspaceService extends Service {
  constructor(ctx,config){super(ctx,'microMulti');this.workspace=config.workspace;this.pluginRoot=config.root;}
}
let root=null, fibers=[], skillFiber=null, skillSignature="";
let attachmentFiber=null, attachmentHome=null;
let contextRoot=null;
let hostProfile=null;
let configLayers=[];
function profileLayers(profile,home){
 const directory=dirname(profile.configPath),layers=[];
 if(existsSync(resolve(directory,'package.json'))){
  const prepared=loadProfileDirectory('Micro-Multi',directory,runtimeRequire.resolve('@deepseek-ai/dsh-app-boot/package.json'),{userLayer:false});
  if(prepared.skippedBundles.length)throw Error('Native profile bundles unavailable: '+prepared.skippedBundles.map(b=>b.packageName).join(', '));
  for(const layer of prepared.layers)layers.push({label:'bundle:'+layer.packageName,patches:layer.patches,paths:layer.patchPaths});
 }
 const homePath=resolve(home,'cordis.patch.yml'),homePatches=loadOptionalPatches('Micro-Multi',homePath);
 if(homePatches)layers.push({label:'home',patches:homePatches,paths:[homePath]});
 for(const path of profile.patchPaths??[])layers.push({label:'profile',patches:loadOverlayPatches('Micro-Multi',path),paths:[path]});
 for(const path of profile.invocationPatchPaths??[])layers.push({label:'invocation',patches:loadOverlayPatches('Micro-Multi',path),paths:[path]});
 return layers;
}
function preserveExpressions(original,next){
 if(JSON.stringify(original)===JSON.stringify(next))return original;
 if(Array.isArray(original)&&Array.isArray(next))return next.map((value,index)=>preserveExpressions(original[index],value));
 if(original&&next&&typeof original==='object'&&typeof next==='object'){
  return Object.fromEntries(Object.entries(next).map(([key,value])=>[key,preserveExpressions(original[key],value)]));
 }
 return next;
}
async function projectContexts(contexts=[],signal){
 const projected=[];
 for(const context of contexts){
  if(!Array.isArray(context.content)){projected.push(context);continue;}
  const content=[];
  for(const block of context.content){
   if(block.type==='image'&&!block.offloaded&&root.get('attachments')){
    try{
     const stored=await root.attachments.readImage(block.attachment,signal);
     if(stored.data.byteLength>10000000)throw Error('Native image exceeds 10 MB');
     const digest=createHash('sha256').update(stored.data).digest('hex');
     mkdirSync(contextRoot,{recursive:true});
     const path=resolve(contextRoot,digest);
     writeFileSync(path,stored.data,{flag:'w'});
     content.push({...block,microMultiImage:{path,sha256:digest,mediaType:stored.ref.mediaType}});
    }catch(error){content.push({...block,microMultiProjectionError:String(error.message??error)});}
   }else if(block.type==='file'&&root.get('attachments')){
    try{content.push({...block,microMultiFilePath:root.attachments.fileHostPath(block.attachment)});}
    catch(error){content.push({...block,microMultiProjectionError:String(error.message??error)});}
   }else content.push(block);
  }
  projected.push({...context,content});
 }
 return projected;
}
async function synchronizeSkills(roots=[]) {
 const paths=[...roots,...[".agents",".opencode",".claude"].map(p=>resolve(root.microMulti.workspace,p,"skills"))];
 const signature=JSON.stringify(paths);
 if(skillFiber&&skillSignature===signature)return;
 if(skillFiber)await skillFiber.dispose();
 skillFiber=root.plugin(SkillFilesystem,{includeDefaultRoots:false,customSkillDirs:paths,watch:true,watchFollowSymlinks:false});
 await skillFiber;skillSignature=signature;
}
const bundles=new Map();
const nativeApprovals=new Map(), nativeCalls=new Map();
const callContext=new AsyncLocalStorage();
setInterval(()=>{if(nativeCalls.size)write({event:'heartbeat'});},5000).unref();
function requestNativeApproval(request,next){
 const requestContext=callContext.getStore();
 if(!requestContext?.approvalBridge)return next();
 const approvalId=randomUUID();
 return new Promise(resolve=>{
  const complete=outcome=>{request.signal?.removeEventListener('abort',onAbort);nativeApprovals.delete(approvalId);resolve(outcome);};
  const onAbort=()=>{write({event:'approval_cancel',approvalId,requestId:requestContext.id});complete('cancelled');};
  nativeApprovals.set(approvalId,complete);
  if(request.signal?.aborted){onAbort();return;}
  request.signal?.addEventListener('abort',onAbort,{once:true});
  write({event:'approval',approvalId,requestId:requestContext.id,toolName:request.toolName,callId:request.callId,reason:request.reason,agentId:request.agent.id});
 });
}
async function dispose(){if(root){const previous=root;root=null;fibers=[];bundles.clear();await previous.fiber.dispose();}}
async function synchronize(plugins,allowPending=false){
 if(attachmentFiber){await attachmentFiber.dispose();attachmentFiber=null;}
 const desired=new Map();
 for(const item of plugins){
  const id=item.bundleId??'default';
  if(!desired.has(id))desired.set(id,[]);
  if(item.bundlePaths){
   const pluginRoot=item.root??root.microMulti.pluginRoot;
   const require=createRequire(resolve(pluginRoot,'package.json'));
   const packageEntry=require.resolve(item.packageName);
   packageRoots.set(item.packageName,pathToFileURL(packageEntry).href);
   const patches=item.bundlePaths.flatMap(path=>loadOverlayPatches('Micro-Multi',path));
   const base=patches.some(patch=>patch.id==='web')?[{id:'web',name:'@deepseek-ai/dsh-web',config:{}}]:[];
   const entries=applyEntryPatches(base,patches,console.warn);
   for(const entry of entries){
    if(entry.disabled)continue;
    const target=entry.name===item.packageName?packageEntry:(()=>{try{return require.resolve(entry.name);}catch{return runtimeRequire.resolve(entry.name);}})();
    desired.get(id).push({entry:target,root:pluginRoot,config:item.configOverrides?.[entry.id]??entry.config??{},bundleId:id});
   }
   if(entries.some(entry=>entry.id==='web'))desired.get(id).push({entry:runtimeRequire.resolve('@deepseek-ai/dsh-tool-web'),root:pluginRoot,config:{searchTimeoutMs:60000,fetch:false},bundleId:id});
  }else desired.get(id).push(item);
 }
 for(const [id,entry] of bundles){
  if(!desired.has(id)||entry.signature!==JSON.stringify(desired.get(id))){
   for(const fiber of entry.fibers)await fiber.dispose();
   bundles.delete(id);
  }
 }
 for(const [id,items] of desired){
  if(bundles.has(id))continue;
  const mounted=[];
  try{
   for(const item of items){
    const imported=await import(pathToFileURL(resolve(item.root??root.microMulti.pluginRoot,item.entry)).href);
    const fiber=root.plugin(imported.default??imported,item.config??{});
    fiber.bundleId=id; mounted.push(fiber);
   }
   for(const fiber of mounted)await fiber;
   bundles.set(id,{signature:JSON.stringify(items),fibers:mounted});
  }catch(error){for(const fiber of mounted)await fiber.dispose();throw error;}
 }
 fibers=[...bundles.values()].flatMap(entry=>entry.fibers);
 if(!root.get('attachments')){attachmentFiber=root.plugin(LocalAttachmentStore,{dshHome:attachmentHome});await attachmentFiber;}
 if(!allowPending)for(const fiber of fibers){
  if(fiber.state!==2){
   const missing=Object.keys(fiber.inject).filter(name=>!root.get(name));
   throw Error(`Plugin ${fiber.name} inactive; missing services: ${missing.join(', ')||'inspect startup log'}`);
  }
 }
}
async function handle(request){
 if(request.action==='init'){
  if(root)throw Error('Cordis host is already initialized');
  process.chdir(request.workspace);
  contextRoot=resolve(request.sessionRoot??request.workspace,'native-contexts');
  attachmentHome=request.sessionRoot??request.workspace;
  hostProfile=request.profile??null;
  const prepare=async context=>{
   root=context;
  await root.plugin(SystemPrompt,{includeHarnessIdentity:false,includeRuntimeContext:false});
  await root.plugin(ToolRuntime,{mode:'native'});
  await root.plugin(WorkspaceService,{workspace:request.workspace,root:request.root});
  await root.plugin(PluginConnection,{});
  await root.plugin(TypertRegistry,{});
  await root.plugin(TypertGateway,{});
  await root.plugin(ApiRemotes,{});
  for(const [plugin,config] of [[AgentRegistry,{}],[SessionStore,{}],[LlmRuntime,{}],
    [SkillRegistry,{}],[ApprovalService,{policy:'ask'}],[SessionProjectionRegistry,{}],
    [JsonlSessionPersistence,{root:resolve(request.sessionRoot??request.workspace,"native-sessions"),compression:"none"}],
    [SubagentRuntime,{}],[LocalFileSystem,{cwd:request.workspace}],[AgentLoop,{}]]){
    const core=root.plugin(plugin,config); await core;
    if(core.state!==2)throw Error(`Core service ${core.name} failed to activate`);
  }
  root.on('approval/request',requestNativeApproval);
  };
  if(request.profile){
   loadEnv('Micro-Multi',request.sessionRoot??request.workspace);
   loadEnv('Micro-Multi',dirname(request.profile.configPath));
   configLayers=profileLayers(request.profile,request.sessionRoot??request.workspace);
   const patches=configLayers.flatMap(layer=>layer.patches);
   root=await boot('Micro-Multi',request.profile.configPath,patches,prepare);
  }else{root=new Context();await prepare(root);}
  await synchronizeSkills(request.skillRoots);
  await synchronize(request.plugins,request.allowPending??false);
  for(const [plugin,providerName] of [[SpawnInProcess,'spawn'],[ForkInProcess,'fork']]){
   if(!root.subagents.getProvider(providerName)){const fiber=root.plugin(plugin,{providerName});await fiber;}
  }
  return {runtime:'native-cordis-host',versions:{cordis:'4.0.4',tools:'0.2.0-rc.1'},
    subagentProviders:root.subagents.list(),
    configLayers:configLayers.map(({label,paths})=>({label,paths})),
    profileEntries:[...(root.get("loader")?.entries()??[])].map(e=>({id:e.id,name:e.options.name,state:e.disabled?"disabled":e.fiber?.state===2?"active":"inactive"})),
    tools:root.tools.schemas(),plugins:fibers.map(f=>({name:f.name,state:f.state===2?'active':'pending',bundleId:f.bundleId}))};
 }
 if(request.action==='dispose'){await dispose();return {disposed:true};}
 if(!root)throw Error('Cordis host has not been initialized');
 if(request.action==='sync'){
  await synchronizeSkills(request.skillRoots);
  await synchronize(request.plugins,true);
  return {tools:root.tools.schemas()};
 }
 if(request.action==='unmount'){
  const entry=bundles.get(request.bundleId);
  if(entry){for(const fiber of entry.fibers)await fiber.dispose();bundles.delete(request.bundleId);}
  fibers=[...bundles.values()].flatMap(entry=>entry.fibers);
  return {unmounted:true};
 }
 if(request.action==='skills')return {skills:await root.skills.list({cwd:root.microMulti.workspace})};
 if(request.action==='chat-run')return await runNativeChat(root,request,write,nativeCalls);
 if(request.action==='schemas')return {tools:root.tools.schemas()};
 if(request.action==='plugin-rpc')return {result:await root.connection.call(request.channel,request.method,request.payload)};
 if(request.action==='plugin-rpc-stream'){
  if(request.channel!=='/api')throw Error('Remote streams require the shared API channel');
  const controller=new AbortController();nativeCalls.set(request.streamId??String(request.id),controller);
  try{
   const empty={async *[Symbol.asyncIterator](){}},stream=await root.typertGateway.wireStream.open(request.method,request.payload,empty,root.connection.operator,controller.signal);
   for await(const value of stream)write({event:'plugin-stream-value',requestId:request.id,streamId:request.streamId,value});
   return {complete:true};
  }finally{nativeCalls.delete(request.streamId??String(request.id));}
 }
 if(request.action==='plugin-models'){
  const providers=root.llm.listProviders();
  return {providers,models:(await Promise.all(providers.map(async provider=>{
   try{return await root.llm.listModels(provider.id);}catch{return [];}
  }))).flat()};
 }
 if(request.action==='plugin-model-stream'){
  const controller=new AbortController();nativeCalls.set(request.streamId??String(request.id),controller);
  try{for await(const chunk of root.llm.stream({...request.options,signal:controller.signal}))write({event:'plugin-model-chunk',requestId:request.id,streamId:request.streamId,chunk});return {complete:true};}
  finally{nativeCalls.delete(request.streamId??String(request.id));}
 }
 if(request.action==='bundle-config'){
  const entries=[];
  for(const [index,item] of request.plugins.entries()){
   if(item.bundlePaths){
    const patches=item.bundlePaths.flatMap(path=>loadOverlayPatches('Micro-Multi',path));
    const base=patches.some(patch=>patch.id==='web')?[{id:'web',name:'@deepseek-ai/dsh-web',config:{}}]:[];
    for(const entry of applyEntryPatches(base,patches,console.warn)){
     if(!entry.disabled)entries.push({key:`${index}:${entry.id}`,name:entry.name,config:item.configOverrides?.[entry.id]??entry.config??{}});
    }
   }else entries.push({key:String(index),name:item.entry,config:item.config??{}});
  }
  return {entries};
 }
 if(request.action==='profile-schema'){
  if(!hostProfile)throw Error('No native profile selected');
  const layers=configLayers;
  const text=renderConfigDump('Micro-Multi',hostProfile.configPath,layers);
  const entries=yaml.load(text,{schema:entryListSchema});
  const profile={name:dirname(hostProfile.configPath).split(/[\\/]/).pop(),dir:dirname(hostProfile.configPath),layers:[],patches:[],skippedBundles:[]};
  const schema=await generateConfigSchema(profile,[[{insert:entries}]],runtimeRequire.resolve('@deepseek-ai/dsh-app-boot/package.json'));
  return {schema,entries};
 }
 if(request.action==='profile-form-patch'){
  if(!hostProfile||!Array.isArray(request.entries))throw Error('Invalid profile form');
  const entries=[...root.loader.entries()];
  const ids=new Set(entries.map(entry=>entry.options.id));
  for(const entry of request.entries){
   if(!ids.has(entry.id)||!entry.config||typeof entry.config!=='object'||Array.isArray(entry.config))throw Error('Invalid profile form entry');
   if(entries.filter(item=>item.options.id===entry.id).length!==1)throw Error('Ambiguous entry id; use the YAML editor for this profile');
   entry.config=preserveExpressions(entries.find(item=>item.options.id===entry.id).options.config,entry.config);
  }
  const patches=hostProfile.patchPaths?.length?loadOverlayPatches('Micro-Multi',hostProfile.patchPaths.at(-1)):[];
  return {patch:yaml.dump([...patches,...request.entries],{schema:entryListSchema})};
 }
 if(request.action==='call'){
  const controller=new AbortController();nativeCalls.set(String(request.id),controller);
  const timer=setTimeout(()=>controller.abort(),Math.min(request.timeoutMs??30000,28800000));
  try{
   const result=await root.tools.execute({callId:String(request.id),name:request.name,
     arguments:request.arguments??{},signal:controller.signal});
   return {isError:result.isError,value:result.value,error:result.error,content:result.content,meta:result.meta,additionalContexts:await projectContexts(result.additionalContexts,controller.signal),concludesTurn:result.concludesTurn};
  }finally{clearTimeout(timer);nativeCalls.delete(String(request.id));}

 }
 throw Error('Unknown Cordis RPC action');
}
let queue=Promise.resolve(), barrier=Promise.resolve(), closing=false;
const active=new Set(),queuedCalls=new Set(),cancelledCalls=new Set();
const blockingActive=new Set();
const executePacket=async request=>{
 try{
  if(request.action==='call'&&cancelledCalls.has(String(request.id)))throw Error('Native call cancelled before dispatch');
  if(closing&&request.action==='call')throw Error('Native Host is closing');
  const result=await callContext.run(request,()=>handle(request));write({id:request.id,result});
 }catch(error){console.error(error.stack??error);write({id:request?.id,error:String(error.message??error).slice(0,2000)});}
 finally{queuedCalls.delete(String(request.id));cancelledCalls.delete(String(request.id));}
};
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{
 if(Buffer.byteLength(line)>500000){process.exit(65);return;}
 let packet;try{packet=JSON.parse(line);}catch{write({error:'Malformed Cordis request'});return;}
 if(packet.action==='bridge-response'||packet.action==='bridge-chunk'){receiveBridge(packet);return;}
 if(packet.action==='approval-response'){
  nativeApprovals.get(packet.approvalId)?.(['allowed-once','rejected','cancelled','unavailable'].includes(packet.outcome)?packet.outcome:'unavailable');return;
 }
 if(packet.action==='cancel-call'){if(queuedCalls.has(String(packet.id)))cancelledCalls.add(String(packet.id));nativeCalls.get(String(packet.id))?.abort();return;}
 if(packet.action==='dispose')for(const controller of nativeCalls.values())controller.abort();
 if(packet.action==='call')queuedCalls.add(String(packet.id));
 queue=queue.then(async()=>{
  await barrier;
  let parallel=['plugin-rpc','plugin-rpc-stream','plugin-model-stream'].includes(packet.action);
  if(packet.action==='call'&&root){
   try{parallel=root.tools.executionMode({callId:String(packet.id),name:packet.name,arguments:packet.arguments??{},signal:AbortSignal.timeout(1000)}).kind==='parallel';}catch{}
  }
  const ready=parallel?barrier:Promise.all([...blockingActive,barrier]);
  const operation=ready.then(()=>executePacket(packet));active.add(operation);
  if(!parallel)barrier=operation;
  if(!['plugin-rpc-stream','plugin-model-stream'].includes(packet.action))blockingActive.add(operation);
  operation.finally(()=>{active.delete(operation);blockingActive.delete(operation);});
 });
});
input.on('close',()=>{closing=true;for(const controller of nativeCalls.values())controller.abort();queue.finally(async()=>{await Promise.all([...active]);await dispose();process.exit(0);});});
process.on('uncaughtException',error=>{console.error(error.stack);process.exit(70);});
process.on('unhandledRejection',error=>{console.error(error);process.exit(70);});
