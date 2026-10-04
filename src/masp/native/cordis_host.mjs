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
import { pathToFileURL,fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { format } from 'node:util';
import {runNativeChat,receiveBridge,bridgeValue} from './chat_runtime.mjs';
import PluginConnection from './plugin_connection.mjs';
import {ClientDependencies} from './client_dependencies.mjs';
import {ServiceDependencies} from './service_dependencies.mjs';
import PluginWebServer from './plugin_webserver.mjs';
import BundleConfigEditor from './plugin_config.mjs';
import LocalCredentials from '@deepseek-ai/dsh-credentials-local';
import {installNamespaceSettings} from './legacy_settings.mjs';
import Loader from '@deepseek-ai/cordis-plugin-loader';
import SettingsForms from '@deepseek-ai/dsh-settings';
import Schema from '@deepseek-ai/schemastery';
import SettingsController from '@deepseek-ai/dsh-api-settings-controller';
class BundleSettingsForms extends SettingsForms {
 bundleSchemas=new WeakMap();
 schema(entry){
  const schema=super.schema(entry);
  // Application bundles support durable remounts as well as live edits. Older
  // clients therefore retain their full form without mutating plugin schemas.
  if(entry.bundleId&&schema){let form=this.bundleSchemas.get(schema);if(!form){form=new Schema(schema.toJSON());form.meta.volatile=true;this.bundleSchemas.set(schema,form);}return form;}
  return schema;
 }
}
import TypertRegistry from '@deepseek-ai/dsh-typert-registry';
import TypertGateway from '@deepseek-ai/dsh-api-gateway';
import * as ApiRemotes from '@deepseek-ai/dsh-api-remotes';
const protocolWrite = process.stdout.write.bind(process.stdout);
const PREFIX = 'MICRO_MULTI_CORDIS:';
const write = (value,limit=500000) => {
  const encoded=JSON.stringify(value);
  if (Buffer.byteLength(encoded)>limit) throw Error('Cordis response exceeds protocol limit');
  protocolWrite(PREFIX+encoded+'\n');
};
// Console output cannot corrupt JSON RPC. Diagnostics remain in the backend-owned log.
for (const name of ['log','info','warn','error','debug']) console[name]=(...args)=>process.stderr.write(format(...args).slice(0,8000)+'\n');
const runtimeRequire=createRequire(import.meta.url);
const available=new Map();
const packageRoots=new Map();
let moduleDependencies,resolvingDependencies=false;
const dependencyRoots=new Set();
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
  if(resolvingDependencies)return nextResolve(specifier,context);
  if(packageRoots.has(specifier))return {url:packageRoots.get(specifier),shortCircuit:true};
  try{return nextResolve(specifier,context);}catch(error){
    if(available.has(specifier))return {url:available.get(specifier),shortCircuit:true};
    try{return {url:pathToFileURL(runtimeRequire.resolve(specifier)).href,shortCircuit:true};}catch{}
    if(moduleDependencies&&!resolvingDependencies&&!specifier.startsWith('.')&&!specifier.includes(':')&&!specifier.startsWith('#')&&context.parentURL?.startsWith('file:')&&[...dependencyRoots].some(path=>context.parentURL.startsWith(path))){
     resolvingDependencies=true;
     try{const parent=fileURLToPath(context.parentURL),require=createRequire(context.parentURL);
      const path=moduleDependencies.resolve(specifier,require,moduleDependencies.owner(parent));
      return {url:pathToFileURL(path).href,shortCircuit:true};
     }finally{resolvingDependencies=false;}
    }
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
let serviceDependencies,namespaceOwners=new Map();
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
const providerOwners=new Map();
function bundleOf(fiber){const seen=new Set();while(fiber){if(seen.has(fiber.uid))return undefined;seen.add(fiber.uid);if(fiber.bundleId)return fiber.bundleId;for(const [id,bundle] of bundles)if(bundle.fibers.some(mounted=>mounted.uid===fiber.uid))return id;const parent=fiber.parent?.fiber;if(parent===fiber)break;fiber=parent;}return undefined;}
function ownedProviderIds(id){return [...providerOwners].filter(([,owners])=>[...owners.values()].some(fiber=>bundleOf(fiber)===id)).map(([provider])=>provider);}
// Cordis traces fiber objects through caller contexts. Match stable runtime uids,
// since application metadata on a returned fiber is not shared by every trace.
for(const method of ['registerAdapter','registerConfigurableProviders']){
 const original=LlmRuntime.prototype[method];
 LlmRuntime.prototype[method]=function(entries,...args){
  const owner=this.ctx.fiber,token=Symbol(method),handle=original.call(this,entries,...args);
  const routes=values=>values.map(value=>typeof value==='string'?value:value.provider);
  let held=routes(entries);
  const remove=()=>{for(const provider of held){const owners=providerOwners.get(provider);owners?.delete(token);if(!owners?.size)providerOwners.delete(provider);}};
  const add=()=>{for(const provider of held){let owners=providerOwners.get(provider);if(!owners)providerOwners.set(provider,owners=new Map());owners.set(token,owner);}};
  add();
  const dispose=()=>{remove();handle();};
  dispose.replace=next=>{handle.replace(next);remove();held=routes(next);add();};
  this.ctx.effect(()=>dispose);
  return dispose;
 };
}
async function cancelable(controller,operation){
 let onAbort;
 const cancelled=new Promise(resolve=>{onAbort=()=>resolve({complete:false,cancelled:true});controller.signal.addEventListener('abort',onAbort,{once:true});});
 try{if(controller.signal.aborted)return {complete:false,cancelled:true};return await Promise.race([Promise.resolve().then(operation),cancelled]);}
 finally{controller.signal.removeEventListener('abort',onAbort);}
}
const nativeApprovals=new Map(), nativeCalls=new Map();
const callContext=new AsyncLocalStorage();
setInterval(()=>{if(nativeCalls.size)write({event:'heartbeat'});},5000).unref();
function requestNativeApproval(request,next){
 const requestContext=callContext.getStore();
 if(!requestContext?.approvalBridge){
  if(requestContext?.action==='chat-run')return bridgeValue(write,requestContext.id,'authorize',{name:request.toolName,arguments:{reason:request.reason,callId:request.callId},agentId:request.agent.id},request.signal).then(allowed=>allowed?'allowed-once':'rejected');
  return 'unavailable';
 }
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
async function dispose(){if(root){const previous=root;root=null;fibers=[];bundles.clear();await previous.fiber.dispose();providerOwners.clear();}}
async function synchronize(plugins,allowPending=false){
 if(attachmentFiber){await attachmentFiber.dispose();attachmentFiber=null;}
 const desired=new Map();
 const packages=[];
 for(const item of plugins){
  const sourceRoot=resolve(item.root??root.microMulti.pluginRoot);
  dependencyRoots.add(pathToFileURL(sourceRoot).href+'/');
  const normalized=sourceRoot.replaceAll('\\','/'),nodeModules=normalized.lastIndexOf('/node_modules/');
  if(nodeModules>=0)dependencyRoots.add(pathToFileURL(normalized.slice(0,nodeModules+14)).href+'/');
  const id=item.bundleId??'default';
  const require=createRequire(resolve(item.root??root.microMulti.pluginRoot,'package.json'));
  try{const manifest=require('./package.json');packages.push({name:manifest.name,require});}catch{}
  if(!desired.has(id))desired.set(id,[]);
  if(item.bundlePaths){
   const pluginRoot=item.root??root.microMulti.pluginRoot;
   const require=createRequire(resolve(pluginRoot,'package.json'));
   const packageEntry=require.resolve(item.packageName);
   packageRoots.set(item.packageName,pathToFileURL(packageEntry).href);
   const patches=item.bundlePaths.flatMap(path=>loadOverlayPatches('Micro-Multi',path));
   // Resolve row-only patches from DSH's own base composition rather than
   // inventing a per-bundle interpretation or ignoring existing-row changes.
   const targets=new Set(patches.map(patch=>patch.id).filter(Boolean));
   const catalog=applyEntryPatches([],loadOverlayPatches('Micro-Multi',runtimeRequire.resolve('@deepseek-ai/dsh-base/cordis.patch.yml')),console.warn);
   const base=catalog.filter(entry=>targets.has(entry.id));
   const entries=applyEntryPatches(base,patches,console.warn);
   for(const entry of entries){
    if(entry.disabled===true)continue;
    const target=entry.name===item.packageName?packageEntry:(()=>{try{return require.resolve(entry.name);}catch{return runtimeRequire.resolve(entry.name);}})();
    desired.get(id).push({entry:target,root:pluginRoot,config:item.configOverrides?.[entry.id]??entry.config??{},id:entry.id,bundleId:id,entryOptions:entry,fromBase:base.some(row=>row.id===entry.id)});
   }
   if(entries.some(entry=>entry.id==='web'))desired.get(id).push({entry:runtimeRequire.resolve('@deepseek-ai/dsh-tool-web'),root:pluginRoot,config:{searchTimeoutMs:60000,fetch:false},bundleId:id});
  }else desired.get(id).push(item);
 }
 await serviceDependencies.prepare(packages);
 for(const [id,entry] of bundles){
  if(!desired.has(id)||entry.signature!==JSON.stringify(desired.get(id))){
   for(const fiber of entry.fibers){fiber.bundleSettingsOff?.();await fiber.dispose();fiber.bundleLoaderOff?.();}
   bundles.delete(id);
  }
 }
 const added=[];
 for(const [id,items] of desired){
  if(bundles.has(id))continue;
  const mounted=[];
  try{
   for(const item of items){
    const imported=await import(pathToFileURL(resolve(item.root??root.microMulti.pluginRoot,item.entry)).href);
    const nativePlugin=imported.default??imported;
    const shared=item.fromBase&&[...(root.registry.get(nativePlugin)?.fibers??[])].find(fiber=>!fiber.bundleId);
    if(shared){shared.update({...shared.config,...item.config},true);await shared;continue;}
    const namespace=item.id||nativePlugin.name||id;
    const editor=root.get('bundleConfigEditor')??root.get('configEditor');
    const base=item.config??{};
    const config=typeof editor?.configFor==='function'?editor.configFor(id,namespace,base):base;
    const loader=root.loader,entryId=item.id||namespace;
    if(loader.store[entryId])throw Error('Ambiguous native Loader entry: '+entryId);
    const options={...item.entryOptions,id:entryId,name:pathToFileURL(resolve(item.root??root.microMulti.pluginRoot,item.entry)).href,config};
    await loader.create(options);const loaded=loader.resolve(entryId),fiber=loaded.fiber;
    if(!fiber){loader.remove(entryId);if(loaded.disabled)continue;throw Error('Native Loader failed to activate '+namespace);}
    fiber.bundleLoaderOff=()=>loader.remove(entryId);
    try{await fiber.await();}catch(error){loader.remove(entryId);throw error;}
    fiber.bundleId=id; mounted.push(fiber);
    if(typeof editor?.configFor==='function'){fiber.bundleSettingsOff=editor.register(id,namespace,fiber,base);}
   }
   for(const fiber of mounted)await fiber;
   bundles.set(id,{signature:JSON.stringify(items),fibers:mounted});
   added.push(id);
  }catch(error){for(const fiber of mounted){fiber.bundleSettingsOff?.();await fiber.dispose();fiber.bundleLoaderOff?.();}throw error;}
 }
 fibers=[...bundles.values()].flatMap(entry=>entry.fibers);
 try{await serviceDependencies.resolve(fibers);}catch(error){
  for(const id of added){const bundle=bundles.get(id);for(const fiber of bundle.fibers){fiber.bundleSettingsOff?.();await fiber.dispose();fiber.bundleLoaderOff?.();}bundles.delete(id);}
  fibers=[...bundles.values()].flatMap(entry=>entry.fibers);throw error;
 }
 if(!root.get('attachments')){attachmentFiber=root.plugin(LocalAttachmentStore,{dshHome:attachmentHome});await attachmentFiber;}
 for(const fiber of fibers)await fiber;
 root.get("settings")?.invalidate();
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
  moduleDependencies=new ClientDependencies(resolve(attachmentHome,'native-dependencies'),runtimeRequire);
  dependencyRoots.clear();dependencyRoots.add(pathToFileURL(moduleDependencies.home).href+'/');
  hostProfile=request.profile??null;
  const prepare=async context=>{
   root=context;
  if(!root.get('dshHomePath'))root.reflect.provide('dshHomePath',(...parts)=>resolve(attachmentHome,...parts));
  const catalog=applyEntryPatches([],loadOverlayPatches('Micro-Multi',runtimeRequire.resolve('@deepseek-ai/dsh-base/cordis.patch.yml')),console.warn);
  serviceDependencies=new ServiceDependencies(root,runtimeRequire,catalog);
  serviceDependencies.discover=async()=>{for(const name of available.keys())if(name.startsWith('@deepseek-ai/'))await serviceDependencies.index(name,runtimeRequire,undefined,false);};
  await root.plugin(SystemPrompt,{includeHarnessIdentity:false,includeRuntimeContext:false});
  await root.plugin(ToolRuntime,{mode:'native'});
  await root.plugin(WorkspaceService,{workspace:request.workspace,root:request.root});
  await root.plugin(PluginConnection,{});
  if(!root.get('credentials'))await root.plugin(LocalCredentials,{dshHome:attachmentHome});
  await root.plugin(PluginWebServer,{});
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
  // The application broker must precede the optional remote answerer: a remote
  // waterfall can wait indefinitely when no native web client is connected.
  root.on('approval/request',requestNativeApproval,{global:true,prepend:true});

  };
  if(request.profile){
   loadEnv('Micro-Multi',request.sessionRoot??request.workspace);
   loadEnv('Micro-Multi',dirname(request.profile.configPath));
   configLayers=profileLayers(request.profile,request.sessionRoot??request.workspace);
   const patches=configLayers.flatMap(layer=>layer.patches);
   root=await boot('Micro-Multi',request.profile.configPath,patches,prepare);
   // Native profile entries and application-installed bundles share the same
   // settings directory, while each editor retains ownership of its writes.
   await root.plugin(BundleConfigEditor,{home:attachmentHome,name:'bundleConfigEditor'});
   const bundleEditor=root.bundleConfigEditor;await bundleEditor.load();
   const editor=root.get('configEditor');
   if(editor){
    const entries=editor.entries.bind(editor),configuration=editor.configuration.bind(editor),edit=editor.edit.bind(editor);
    editor.entries=()=>[...entries(),...bundleEditor.entries()];
    editor.configuration=()=>[...configuration(),...bundleEditor.configuration()];
    editor.edit=(entry,change)=>entry.bundleId?bundleEditor.edit(entry,change):edit(entry,change);
   }else root.reflect.provide('configEditor',bundleEditor);
  }else{
   root=new Context();await prepare(root);
   await root.plugin(BundleConfigEditor,{home:attachmentHome});await root.configEditor.load();
   root.reflect.provide('profileContext',{home:attachmentHome,name:'application-bundles'});
   await root.plugin(Loader,{baseUrl:pathToFileURL(resolve(request.root,'package.json')).href});
  }
  if(root.get('configEditor')&&root.get('profileContext')&&!root.get('settings'))await root.plugin(BundleSettingsForms,{});
  if(request.profile&&root.get('settings')){
   const settings=root.settings,original=settings.schema.bind(settings),cache=new WeakMap();
   settings.schema=entry=>{const schema=original(entry);if(!entry.bundleId||!schema)return schema;let form=cache.get(schema);if(!form){form=new Schema(schema.toJSON());form.meta.volatile=true;cache.set(schema,form);}return form;};
  }
  namespaceOwners=await installNamespaceSettings(root,attachmentHome);
  await root.plugin(SettingsController,{});
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
  if(entry){for(const fiber of entry.fibers){fiber.bundleSettingsOff?.();await fiber.dispose();fiber.bundleLoaderOff?.();}bundles.delete(request.bundleId);}
  fibers=[...bundles.values()].flatMap(entry=>entry.fibers);
  return {unmounted:true};
 }
 if(request.action==='skills')return {skills:await root.skills.list({cwd:root.microMulti.workspace})};
 if(request.action==='chat-run')return await runNativeChat(root,request,write,nativeCalls);
 if(request.action==='schemas')return {tools:root.tools.schemas()};
 if(request.action==='plugin-rpc')return {result:await root.connection.call(request.channel,request.method,request.payload)};
 if(request.action==='plugin-index')return {html:root.webServer.renderIndex(request.html)};
 if(request.action==='plugin-http-endpoint'){await root.webServer.ready;return {url:'http://127.0.0.1:'+root.webServer.server.address().port};}
 if(request.action==='plugin-http')return await root.webServer.request(request);
 if(request.action==='plugin-attachment'){
  const stored=await root.attachments.readImage(request.reference);
  return {attachment:stored.ref,data:Buffer.from(stored.data).toString('base64')};
 }
 if(request.action==='plugin-capabilities')return {providesModels:Boolean(ownedProviderIds(request.pluginId).length),settingsNamespaces:[...new Set([...(root.get('bundleConfigEditor')??root.get('configEditor'))?.entries().filter(entry=>entry.bundleId===request.pluginId).map(entry=>entry.options.id)??[],...[...namespaceOwners].filter(([,fiber])=>bundleOf(fiber)===request.pluginId).map(([ns])=>ns)])]};
 if(request.action==='plugin-rpc-stream'){
  const controller=new AbortController();nativeCalls.set(request.streamId??String(request.id),controller);
  try{
   return await cancelable(controller,async()=>{
    const empty={async *[Symbol.asyncIterator](){}},stream=request.channel==='/api'?await root.typertGateway.wireStream.open(request.method,request.payload,empty,root.connection.operator,controller.signal):await root.connection.dispatch(request.channel,request.method,request.payload,controller.signal);
    if(!stream?.[Symbol.asyncIterator])throw Error('Plugin RPC endpoint did not return a stream');
    for await(const value of stream){if(controller.signal.aborted)break;write({event:'plugin-stream-value',requestId:request.id,streamId:request.streamId,value});}
    return {complete:true};
   });
  }finally{nativeCalls.delete(request.streamId??String(request.id));}
 }
 if(request.action==='plugin-models'){
  const owned=request.pluginId?new Set(ownedProviderIds(request.pluginId)):null;
  const providers=root.llm.listProviders().filter(provider=>!owned||owned.has(provider.id));
  const failures=[];
  return {providers,models:(await Promise.all(providers.map(async provider=>{
   let timer;
   const discover=async()=>{const models=await root.llm.listModels(provider.id);return await Promise.all(models.map(async model=>{try{return {...model,...await root.llm.resolveModelInfo(provider.id,model.id,AbortSignal.timeout(10000))};}catch{return model;}}));};
   try{return await Promise.race([discover(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Model discovery timed out')),15000);})]);}
   catch(error){failures.push({provider:provider.id,error:String(error.message??error)});return [];}
   finally{clearTimeout(timer);}
  }))).flat(),failures};
 }
 if(request.action==='plugin-model-stream'){
  const controller=new AbortController();nativeCalls.set(request.streamId??String(request.id),controller);
  try{
   let imageBytes=0;
   const messages=[];
   for(const message of request.options.messages){const content=[];for(const block of message.content){
    if(block.type!=='micro-multi-image'){content.push(block);continue;}
    const data=Buffer.from(block.data,'base64');imageBytes+=data.length;
    if(data.length>10*1024*1024||imageBytes>25*1024*1024)throw Error('Image input exceeds attachment limits');
    const attachment=await root.attachments.saveImage({data,mediaType:block.mediaType});content.push({type:'image',attachment});
   }messages.push({...message,content});}
   return await cancelable(controller,async()=>{for await(const chunk of root.llm.stream({...request.options,messages,signal:controller.signal})){if(controller.signal.aborted)break;write({event:'plugin-model-chunk',requestId:request.id,streamId:request.streamId,chunk});}return {complete:true};});
  }
  finally{nativeCalls.delete(request.streamId??String(request.id));}
 }
 if(request.action==='bundle-config'){
  const entries=[];
  for(const [index,item] of request.plugins.entries()){
   if(item.bundlePaths){
    const patches=item.bundlePaths.flatMap(path=>loadOverlayPatches('Micro-Multi',path));
    // Resolve row-only patches from DSH's own base composition rather than
   // inventing a per-bundle interpretation or ignoring existing-row changes.
   const targets=new Set(patches.map(patch=>patch.id).filter(Boolean));
   const catalog=applyEntryPatches([],loadOverlayPatches('Micro-Multi',runtimeRequire.resolve('@deepseek-ai/dsh-base/cordis.patch.yml')),console.warn);
   const base=catalog.filter(entry=>targets.has(entry.id));
    for(const entry of applyEntryPatches(base,patches,console.warn)){
     if(!entry.disabled)entries.push({key:`${index}:${entry.id}`,name:entry.name,config:(root.get('bundleConfigEditor')??root.configEditor).configFor(request.pluginId??item.bundleId??'default',entry.id,item.configOverrides?.[entry.id]??entry.config??{})});
    }
   }else{
    const bundleId=request.pluginId??item.bundleId??'default',fiber=bundles.get(bundleId)?.fibers[index];
    const editor=root.get('bundleConfigEditor')??root.configEditor;
    const namespace=item.id??fiber?.name??bundleId;
    entries.push({key:String(index),name:item.entry,config:editor.configFor(bundleId,namespace,item.config??{})});
   }
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
  if(cancelledCalls.has(String(request.streamId??request.id)))throw Error('Native call cancelled before dispatch');
  if(closing&&request.action==='call')throw Error('Native Host is closing');
  const result=await callContext.run(request,()=>handle(request));write({id:request.id,result},['plugin-http','plugin-attachment','plugin-index'].includes(request.action)?36*1024*1024:500000);
 }catch(error){console.error(error.stack??error);write({id:request?.id,error:String(error.message??error).slice(0,2000)});}
 finally{queuedCalls.delete(String(request.streamId??request.id));cancelledCalls.delete(String(request.streamId??request.id));}
};
const input=createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{
 if(Buffer.byteLength(line)>36*1024*1024){process.exit(65);return;}
 let packet;try{packet=JSON.parse(line);}catch{write({error:'Malformed Cordis request'});return;}
 if(!['plugin-http','plugin-model-stream','plugin-index'].includes(packet.action)&&Buffer.byteLength(line)>500000){write({id:packet.id,error:'Cordis request exceeds 500 KB'});return;}
 if(packet.action==='bridge-response'||packet.action==='bridge-chunk'){receiveBridge(packet);return;}
 if(packet.action==='approval-response'){
  nativeApprovals.get(packet.approvalId)?.(['allowed-once','rejected','cancelled','unavailable'].includes(packet.outcome)?packet.outcome:'unavailable');return;
 }
 if(packet.action==='cancel-call'){const id=String(packet.id);cancelledCalls.add(id);setTimeout(()=>cancelledCalls.delete(id),60000).unref();nativeCalls.get(id)?.abort();return;}
 if(packet.action==='dispose')for(const controller of nativeCalls.values())controller.abort();
 if(['call','plugin-rpc-stream','plugin-model-stream'].includes(packet.action))queuedCalls.add(String(packet.streamId??packet.id));
 queue=queue.then(async()=>{
  await barrier;
  let parallel=['plugin-http','plugin-rpc','plugin-rpc-stream','plugin-model-stream','plugin-models','plugin-attachment'].includes(packet.action);
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
