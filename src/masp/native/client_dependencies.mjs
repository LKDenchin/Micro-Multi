/** Resolve the DSH client graph, including packages only declared by inject/external. */
import {createRequire} from 'node:module';
import {existsSync,readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {dirname,resolve,delimiter} from 'node:path';
import {execFileSync} from 'node:child_process';
import semver from 'semver';
export class ClientDependencies {
 constructor(home,runtimeRequire){this.home=resolve(home);this.runtimeRequire=runtimeRequire;try{this.hostVersion=JSON.parse(readFileSync(runtimeRequire.resolve('@deepseek-ai/dsh-settings/package.json'),'utf8')).version;}catch{}this.installed=new Set();mkdirSync(this.home,{recursive:true});const path=resolve(this.home,'package.json');if(!existsSync(path))writeFileSync(path,JSON.stringify({private:true}));this.require=createRequire(path);this.versionsPath=resolve(this.home,'dsh-versions.json');try{this.versions=JSON.parse(readFileSync(this.versionsPath,'utf8'));}catch{this.versions={};}}
 metadata(name,require){
  try{const own=require.resolve('./package.json');if(JSON.parse(readFileSync(own,'utf8')).name===name)return own;}catch{}
  try{return require.resolve(name+'/package.json');}catch(error){
   // package.json need not be a public export.
   let file;for(const spec of [name+'/client',name])try{file=require.resolve(spec);break;}catch{}
   if(file)for(let dir=dirname(file);dir!==dirname(dir);dir=dirname(dir)){const path=resolve(dir,'package.json');if(existsSync(path)&&JSON.parse(readFileSync(path,'utf8')).name===name)return path;}
   throw error;
  }
 }
 owner(file){for(let dir=dirname(file);dir!==dirname(dir);dir=dirname(dir)){const path=resolve(dir,'package.json');if(existsSync(path))return JSON.parse(readFileSync(path,'utf8'));}return {};}
 exported(spec,path){
  const pkg=JSON.parse(readFileSync(path,'utf8')),subpath=spec.slice(pkg.name.length),key=subpath?'.'+subpath:'.';
  let target=pkg.exports;
  if(target&&typeof target==='object'&&!Array.isArray(target)&&Object.keys(target).some(key=>key.startsWith('.'))){
   const match=Object.keys(target).find(pattern=>pattern.includes('*')&&key.startsWith(pattern.split('*')[0])&&key.endsWith(pattern.split('*')[1]));
   target=target[key]??(match?target[match]:undefined);
   if(match&&typeof target==='string')target=target.replaceAll('*',key.slice(match.split('*')[0].length,key.length-match.split('*')[1].length));
  }
  const choose=value=>typeof value==='string'?value:Array.isArray(value)?value.map(choose).find(Boolean):value&&typeof value==='object'?choose(value.browser??value.import??value.default??value.require):undefined;
  target=choose(target);
  if(!target&&!pkg.exports)target=subpath?'.'+subpath:'./'+(pkg.main??'index.js');
  if(typeof target!=='string'||!target.startsWith('.'))throw Error('Package has no runtime export '+spec);
  const file=resolve(dirname(path),target);if(!existsSync(file))throw Error('Package export has no built artifact: '+file);return file;
 }
 npm(args){
  const dirs=[dirname(process.execPath),...(process.env.PATH??'').split(delimiter)];
  const cli=dirs.flatMap(dir=>[resolve(dir,'node_modules/npm/bin/npm-cli.js'),resolve(dir,'../lib/node_modules/npm/bin/npm-cli.js')]).find(existsSync);
  if(!cli)throw Error('npm runtime is required to provision declared client dependencies');
  const env={...process.env,NODE_ENV:'development',ELECTRON_RUN_AS_NODE:'1'};for(const key of Object.keys(env))if(/^npm_config_(omit|production|only)$/i.test(key))delete env[key];
  return execFileSync(process.execPath,[cli,...args],{cwd:this.home,env,encoding:'utf8',timeout:180000,windowsHide:true,stdio:['ignore','pipe','pipe']});
 }
 ensure(name,require,owner={}){
  let declared=owner.dependencies?.[name]??owner.peerDependencies?.[name]??owner.devDependencies?.[name];
  const sdk=name.startsWith('@deepseek-ai/dsh-')&&this.hostVersion;
  if(sdk){
   // DSH framework modules share one ABI. Plugin development ranges must not
   // replace a host SDK module or mix older framework versions in one graph.
   try{return this.metadata(name,this.runtimeRequire);}catch{}
   try{const path=this.metadata(name,this.require);if(JSON.parse(readFileSync(path,'utf8')).version===this.hostVersion)return path;}catch{}
   const key=this.hostVersion+':'+name;
   if(!this.versions[key]){const raw=JSON.parse(this.npm(['view',name,'versions','--json'])),list=(Array.isArray(raw)?raw:[raw]).filter(value=>semver.valid(value)).sort(semver.compare);this.versions[key]=list.includes(this.hostVersion)?this.hostVersion:list.filter(value=>semver.lte(value,this.hostVersion)).at(-1);if(!this.versions[key])throw Error('No compatible published SDK version: '+name);writeFileSync(this.versionsPath,JSON.stringify(this.versions));}
   declared=this.versions[key];
  }
  for(const resolver of [require,this.runtimeRequire,this.require])try{const path=this.metadata(name,resolver),version=JSON.parse(readFileSync(path,'utf8')).version;if(declared?(!semver.validRange(declared)||semver.satisfies(version,declared,{includePrerelease:true})):(!name.startsWith('@deepseek-ai/')||!this.hostVersion||semver.lte(version,this.hostVersion)))return path;}catch{}
  if(!/^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/.test(name))throw Error('Invalid declared client package: '+name);
  if(this.installed.has(name))throw Error('Declared client dependency unavailable after installation: '+name);
  // DSH's latest tag may point at an older prerelease. Use the actual published
  // versions for an undeclared injection, instead of assuming the host version exists.
  let version=declared;
  if(!version){const versions=JSON.parse(this.npm(['view',name,'versions','--json']));const list=(Array.isArray(versions)?versions:[versions]).filter(value=>semver.valid(value)).sort(semver.compare);let host;try{host=JSON.parse(readFileSync(this.runtimeRequire.resolve('@deepseek-ai/dsh-settings/package.json'),'utf8')).version;}catch{}version=name.startsWith('@deepseek-ai/')&&host?(list.includes(host)?host:list.filter(value=>semver.lte(value,host)).at(-1)):list.at(-1);}
  if(typeof version!=='string'||!version)throw Error('No published version for client dependency: '+name);
  this.npm(['install','--ignore-scripts','--legacy-peer-deps','--include=optional','--no-audit','--no-fund','--save-exact','--',name+'@'+version]);this.installed.add(name);
  return this.metadata(name,this.require);
 }
 resolve(spec,require,owner){
  for(const resolver of [require,this.runtimeRequire,this.require])try{return resolver.resolve(spec);}catch{}
  const name=spec.startsWith('@')?spec.split('/').slice(0,2).join('/'):spec.split('/')[0];
  // Node caches absent package scopes. Read a freshly installed export directly
  // so the first installation works in this process, without a second launch.
  const metadata=this.ensure(name,require,owner);return this.exported(spec,metadata);
 }
}
