import {clientSource} from './client_source.mjs';
import {ClientDependencies} from './client_dependencies.mjs';
import {frameworkSource} from './framework_guard.mjs';
/** Compile only a selected installed plugin, never the DSH WebUI. */
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {readFileSync,mkdirSync,readdirSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const [packageRoot,output]=process.argv.slice(2),runtimeRequire=createRequire(import.meta.url);
const manifest=JSON.parse(readFileSync(resolve(packageRoot,'package.json'),'utf8'));
const pluginRequire=createRequire(resolve(packageRoot,'package.json'));
const provision=new ClientDependencies(resolve(output,'../dependencies'),runtimeRequire);
const entry=pluginRequire.resolve(manifest.name+'/client');
const supplied=new Set(['@deepseek-ai/dsh-client-runtime','@deepseek-ai/dsh-client-ui-theme','@deepseek-ai/dsh-client-connection','@deepseek-ai/dsh-client-locale','@deepseek-ai/dsh-client-ui-renderer','@deepseek-ai/dsh-client-ui-settings','@deepseek-ai/dsh-client-ui-model-selection','@deepseek-ai/dsh-api-gateway','@deepseek-ai/dsh-api-remotes','@deepseek-ai/dsh-typert-registry']);

const dependencies=[],dependencyNames=[],visited=new Set([manifest.name]);
function collect(name,require,owner=manifest){
 if(supplied.has(name)||visited.has(name))return;
 visited.add(name);
 const packagePath=provision.ensure(name,require,owner);
 const dependency=JSON.parse(readFileSync(packagePath,'utf8')),nested=createRequire(packagePath);
 if(!dependency.dsh?.client)return;
 for(const name of dependency.dsh.client.inject??[])collect(name,nested,dependency);
 dependencies.push(provision.exported(name+'/client',packagePath));dependencyNames.push(name);
}
for(const name of manifest.dsh?.client?.inject??[])collect(name,pluginRequire);
const syntax=[entry,...dependencies].map(path=>clientSource(frameworkSource(path)??readFileSync(path,'utf8')));
const clientSlots=[...new Set(syntax.flatMap(row=>row.slots))],nativeChildren=[...new Set(syntax.flatMap(row=>row.children))];
mkdirSync(output,{recursive:true});
await build({entryPoints:[resolve(dirname(fileURLToPath(import.meta.url)),'plugin_client.mjs')],outfile:resolve(output,'client.js'),bundle:true,format:'esm',platform:'browser',target:'es2022',minify:true,jsx:'automatic',loader:{'.module.css':'local-css','.woff2':'dataurl','.woff':'dataurl','.ttf':'dataurl'},define:{'process.env.NODE_ENV':'"production"','import.meta.env.MODE':'"production"','process.env.CORDIS_SHARED':'undefined','process.execArgv':'[]','process.versions.node':'"0.0.0"'},plugins:[{name:'shared-runtime',setup(builder){builder.onResolve({filter:/.*/},args=>{
 if(/^[A-Za-z]:[\\/]/.test(args.path)||args.path.startsWith('/'))return {path:args.path};
 if(args.path==='micro-multi:react-dom-native')return {path:runtimeRequire.resolve('react-dom')};
 if(args.path==='react-dom'&&!args.importer.replaceAll('\\','/').includes('/node_modules/react-dom/'))return {path:resolve(dirname(fileURLToPath(import.meta.url)),'plugin_portals.mjs')};
 if(args.path==='node:module')return {path:args.path,namespace:'node-shim'};
 if(args.path==='micro-multi:native-modules')return {path:args.path,namespace:'native-modules'};
 if(args.path==='micro-multi:plugin-client')return {path:entry};
 if(args.path==='micro-multi:client-dependencies')return {path:args.path,namespace:'dependencies'};
 if(args.path==='cordis')return {path:runtimeRequire.resolve('@deepseek-ai/cordis')};
 if(['react','react/jsx-runtime','react/jsx-dev-runtime','react-dom','react-dom/client','@deepseek-ai/cordis'].includes(args.path))return {path:runtimeRequire.resolve(args.path)};
 if(args.path.startsWith('@deepseek-ai/')){try{return {path:runtimeRequire.resolve(args.path)};}catch{}}
 if(!['url-token','import-rule'].includes(args.kind)&&!args.path.startsWith('.')&&!args.path.startsWith('/')&&!/^[A-Za-z]:/.test(args.path)&&!args.path.startsWith('node:')){
 const requester=args.importer&&!args.importer.startsWith('micro-multi:')?createRequire(args.importer):runtimeRequire;
 try{return {path:provision.resolve(args.path,requester,args.importer&&!args.importer.startsWith('micro-multi:')?provision.owner(args.importer):manifest)};}catch(error){throw Error('Client module '+args.path+' required by '+args.importer+': '+error.message);}
 }
});builder.onLoad({filter:/.*/,namespace:'dependencies'},()=>({contents:dependencies.map((path,index)=>'import * as dependency'+index+' from '+JSON.stringify(path)+';').join('\n')+'\nexport const nativeChildren='+JSON.stringify(nativeChildren)+';\nexport const dependencyNames='+JSON.stringify(dependencyNames)+';\nexport const packageName='+JSON.stringify(manifest.name)+';\nexport const clientSlots='+JSON.stringify(clientSlots)+';\nexport default ['+dependencies.map((_,index)=>'dependency'+index).join(',')+'];',loader:'js'}));
builder.onLoad({filter:/.*/,namespace:'node-shim'},()=>({contents:'export function createRequire(){return ()=>{throw Error("Node internals unavailable in browser");};}',loader:'js'}));
builder.onLoad({filter:/.*/,namespace:'native-modules'},()=>({contents:`import bootstrap from '@deepseek-ai/dsh-client-modules/client';
export const modules=bootstrap.createClientModuleSystem({mode:'queue',pendingQueue:[]},{id:'@deepseek-ai/dsh-client-modules',exports:bootstrap},{boot:{rev:'embedded',entries:[],batches:[]},staticModules:{}});`,loader:'js',resolveDir:dirname(fileURLToPath(import.meta.url))}));
builder.onLoad({filter:/\.js$/},args=>{
 const source=frameworkSource(args.path)??readFileSync(args.path,'utf8');
 if(!source.includes('window.__ModuleLoader__.load('))return frameworkSource(args.path)===undefined?undefined:{contents:source,loader:'js',resolveDir:dirname(args.path)};
 const isBootstrap=args.path.replaceAll('\\','/').endsWith('/dsh-client-modules/lib/client.js');
 if(isBootstrap)return {contents:'let captured;const capture={load(entry){captured=entry.factory(()=>{throw Error("Unexpected bootstrap dependency");});}};\n'+source.replace('window.__ModuleLoader__.load(','capture.load(')+'\nexport default captured;',loader:'js',resolveDir:dirname(args.path)};
 const owner=provision.owner(args.path);
 const names=[...new Set([...clientSource(source).imports,...(owner.dsh?.client?.external??[])])];
 const imports=names.map((name,index)=>{let spec=name==='cordis'?'@deepseek-ai/cordis':name;if(name!=='cordis'&&/^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/.test(name)){const path=provision.ensure(name,createRequire(args.path),owner),metadata=JSON.parse(readFileSync(path,'utf8'));if(metadata.dsh?.client)spec=name+'/client';}return 'import * as module'+index+' from '+JSON.stringify(spec)+';';}).join('\n');
 const table=names.map((name,index)=>JSON.stringify(name)+':legacyModule(module'+index+')').join(',');
 const chunks=/\/client\.js$/.test(args.path.replaceAll('\\','/'))?readdirSync(dirname(args.path)).filter(name=>/^client\.[A-Za-z0-9][A-Za-z0-9._-]*\.js$/.test(name)):[];
 const chunkImports=chunks.map(name=>'import '+JSON.stringify('./'+name)+';').join('\n');
 return {contents:imports+'\nimport {modules} from "micro-multi:native-modules";\n'+chunkImports+'\nfunction legacyModule(namespace){const value=namespace.default??namespace;return new Proxy(value,{get(target,key){if(key in target)return target[key];if(typeof key==="string"&&/^Icon.+[0-9]+$/.test(key)){const stem=key.replace(/[0-9]+$/,"");return target[stem+"Regular"]??target[stem+"Medium"]??target[stem];}return undefined;}});}\nlet captured;const table={'+table+'};for(const [id,value] of Object.entries(table))modules.seed.set(id,value);const capture={load(entry){modules.register(entry);if(entry.chunk===undefined)captured=modules.materialize(entry.id.replace(/\\/client$/,"")).exports;}};\n'+source.replaceAll('window.__ModuleLoader__.load(','capture.load(')+'\nexport default captured;',loader:'js',resolveDir:dirname(args.path)};
});}}]});
