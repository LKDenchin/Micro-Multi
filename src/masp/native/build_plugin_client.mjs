/** Compile only a selected installed plugin, never the DSH WebUI. */
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {readFileSync,mkdirSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const [packageRoot,output]=process.argv.slice(2),runtimeRequire=createRequire(import.meta.url);
const manifest=JSON.parse(readFileSync(resolve(packageRoot,'package.json'),'utf8'));
const pluginRequire=createRequire(resolve(packageRoot,'package.json'));
const entry=pluginRequire.resolve(manifest.name+'/client');
const supplied=new Set(['@deepseek-ai/dsh-client-connection','@deepseek-ai/dsh-client-locale','@deepseek-ai/dsh-client-ui-renderer','@deepseek-ai/dsh-client-ui-settings','@deepseek-ai/dsh-client-ui-model-selection','@deepseek-ai/dsh-api-gateway','@deepseek-ai/dsh-api-remotes','@deepseek-ai/dsh-typert-registry']);
const dependencies=[],visited=new Set([manifest.name]);
function collect(name,require){
 if(supplied.has(name)||visited.has(name))return;
 visited.add(name);
 let packagePath;try{packagePath=require.resolve(name+'/package.json');}catch{packagePath=runtimeRequire.resolve(name+'/package.json');}
 const dependency=JSON.parse(readFileSync(packagePath,'utf8')),nested=createRequire(packagePath);
 if(!dependency.dsh?.client)return;
 for(const name of dependency.dsh.client.inject??[])collect(name,nested);
 dependencies.push(nested.resolve(name+'/client'));
}
for(const name of manifest.dsh?.client?.inject??[])collect(name,pluginRequire);
mkdirSync(output,{recursive:true});
await build({entryPoints:[resolve(dirname(fileURLToPath(import.meta.url)),'plugin_client.mjs')],outfile:resolve(output,'client.js'),bundle:true,format:'esm',platform:'browser',target:'es2022',minify:true,jsx:'automatic',loader:{'.module.css':'local-css','.woff2':'dataurl','.woff':'dataurl','.ttf':'dataurl'},define:{'process.env.NODE_ENV':'"production"','import.meta.env.MODE':'"production"'},plugins:[{name:'shared-runtime',setup(builder){builder.onResolve({filter:/.*/},args=>{
 if(args.path==='micro-multi:plugin-client')return {path:entry};
 if(args.path==='micro-multi:client-dependencies')return {path:args.path,namespace:'dependencies'};
 if(['react','react/jsx-runtime','react/jsx-dev-runtime','react-dom','react-dom/client','@deepseek-ai/cordis'].includes(args.path))return {path:runtimeRequire.resolve(args.path)};
 if(args.path.startsWith('@deepseek-ai/')){try{return {path:runtimeRequire.resolve(args.path)};}catch{}}
});builder.onLoad({filter:/.*/,namespace:'dependencies'},()=>({contents:dependencies.map((path,index)=>'import * as dependency'+index+' from '+JSON.stringify(path)+';').join('\n')+'\nexport default ['+dependencies.map((_,index)=>'dependency'+index).join(',')+'];',loader:'js'}));
builder.onLoad({filter:/[\\/]lib[\\/].*\.js$/},args=>{
 const source=readFileSync(args.path,'utf8');
 if(!source.includes('window.__ModuleLoader__.load('))return;
 const names=[...new Set([...source.matchAll(/\brequire\("([^"\n]+)"\)/g)].map(match=>match[1]))];
 const imports=names.map((name,index)=>'import * as module'+index+' from '+JSON.stringify(name)+';').join('\n');
 const table=names.map((name,index)=>JSON.stringify(name)+':(module'+index+'.default??module'+index+')').join(',');
 return {contents:imports+'\nlet captured; const table={'+table+'}; const capture={load(entry){captured=entry.factory(id=>{if(!(id in table))throw Error("Missing client module: "+id);return table[id];});}};\n'+source.replace('window.__ModuleLoader__.load(','capture.load(')+'\nexport default captured;',loader:'js',resolveDir:dirname(args.path)};
});}}]});
