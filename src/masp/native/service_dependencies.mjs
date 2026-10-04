/** Resolve Cordis service dependencies from the installed provider catalog. */
import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {interpolate} from '@deepseek-ai/cordis-plugin-loader';
import {frameworkSource} from './framework_guard.mjs';
import {Inject} from '@deepseek-ai/cordis';

export class ServiceDependencies {
 constructor(ctx,require,entries){this.ctx=ctx;this.require=require;this.entries=entries;this.providers=new Map();this.indexed=new Set();this.mounted=new Map();}
 async index(name,require=this.require,entry,recurse=true){
  let path;try{path=require.resolve(name);}catch{return;}
  if(this.indexed.has(path)){if(entry)for(const provider of this.providers.values())if(provider.path===path)provider.entry=entry;return;}this.indexed.add(path);
  // Discovery reads source only. Importing the entire catalog delays every new
  // host, including approval requests, and executes unrelated module globals.
  const sources=[frameworkSource(path)??readFileSync(path,'utf8')];
  const nested=createRequire(path);
  for(const source of [...sources])for(const parent of new Set([...source.matchAll(/\bextends\s+(\w+)/g)].map(match=>match[1]))){
   if(parent==='Service')continue;
   for(const declaration of source.matchAll(/import\s+([^;]*?)\s+from\s+(['"])([^'"]+)\2/g))if(new RegExp('\\b'+parent+'\\b').test(declaration[1]))try{const inherited=nested.resolve(declaration[3]);sources.push(frameworkSource(inherited)??readFileSync(inherited,'utf8'));}catch{}
  }
  for(const declaration of sources[0].matchAll(/export\s+[^;]*?from\s+(['"])(\.[^'"]+)\1/g))try{const reexport=nested.resolve(declaration[2]);sources.push(frameworkSource(reexport)??readFileSync(reexport,'utf8'));}catch{}
  const services=new Set();
  for(const source of sources){
   for(const match of source.matchAll(/(?:super\(\s*\w+\s*,\s*|(?:\.provide|\.reflect\.provide)\(\s*)(['"])([^'"]+)\1/g))services.add(match[2]);
   for(const match of source.matchAll(/storageBackendServiceKey\(\s*(['"])([^'"]+)\1/g))services.add('storage.backend.'+match[2]);
   for(const match of source.matchAll(/static\s+provide\s*=\s*(['"])([^'"]+)\1/g))services.add(match[2]);
  }
  for(const service of services)if(!this.providers.has(service)||entry&&!this.providers.get(service).entry)this.providers.set(service,{path,entry});
  if(recurse)try{
   const packagePath=require.resolve(name+'/package.json'),manifest=JSON.parse(readFileSync(packagePath,'utf8')),nested=createRequire(packagePath);
   for(const dependency of Object.keys({...manifest.dependencies,...manifest.peerDependencies})){
    if(dependency.startsWith('@deepseek-ai/')){await this.index(dependency,nested);continue;}
    try{const metadata=JSON.parse(readFileSync(nested.resolve(dependency+'/package.json'),'utf8')),deps={...metadata.dependencies,...metadata.peerDependencies};if(metadata.dsh||deps.cordis||deps['@deepseek-ai/cordis'])await this.index(dependency,nested);}catch{}
   }
  }catch{}
 }
 async prepare(packages=[]){
  this.packages=packages;
  if(this.prepared)for(const {name,require} of packages)await this.index(name,require);
 }
 async catalog(){
  if(this.prepared)return;this.prepared=true;
  // Canonical composition wins over abstract service interfaces and variants.
  for(const entry of this.entries)await this.index(entry.name,this.require,entry,false);
  for(const {name,require} of this.packages??[])await this.index(name,require);
 }
 required(plugin){return Object.keys(Inject.resolve(plugin.inject));}
 async ensure(service,chain=[]){
  if(this.ctx.get(service))return;
  if(chain.includes(service))throw Error('Circular service dependency: '+[...chain,service].join(' -> '));
  await this.catalog();
  if(!this.providers.has(service)&&this.discover){await this.discover();this.discover=null;}
  const provider=this.providers.get(service);
  if(!provider)throw Error('Cordis tool failed: No installed provider for service '+service+' (dependency chain: '+[...chain,service].join(' -> ')+')');
  await this.activate(provider,[...chain,service]);
  if(!this.ctx.get(service))throw Error('Provider '+provider.path+' did not register service '+service);
 }
 async activate(provider,chain){
  if(this.mounted.has(provider.path)){await this.mounted.get(provider.path).await();return;}
  if(!provider.plugin){const module=await import(pathToFileURL(provider.path).href);provider.plugin=module.default??module;}
  const {plugin,entry}=provider;
  for(const service of this.required(plugin))await this.ensure(service,chain);
  const config=interpolate(this.ctx,entry?.config??{});
  // Domain backends are selected by configuration, rather than static inject.
  // Their lifecycle services are discoverable from the same provider catalog.
  for(const backend of new Set([config.backend,...Object.values(config.routes??{})].filter(value=>typeof value==='string'))){
   const service='storage.backend.'+backend;if(this.providers.has(service))await this.ensure(service,chain);
  }
  const loader=this.ctx.loader,id=await loader.create({...entry,id:entry?.id??'provider-'+randomUUID(),name:pathToFileURL(provider.path).href,config});
  const fiber=loader.resolve(id).fiber;
  if(!fiber){loader.remove(id);throw Error('Native Loader failed to load service provider '+provider.path);}
  this.mounted.set(provider.path,fiber);
  try{await fiber.await();}catch(error){this.mounted.delete(provider.path);loader.remove(id);throw error;}
  if(fiber.state!==2)throw Error('Service provider '+fiber.name+' failed to activate');
 }
 async resolve(fibers){
  for(const fiber of fibers)for(const service of Object.keys(fiber.inject))if(!this.ctx.get(service))await this.ensure(service);
  for(const fiber of fibers){await fiber.await();if(fiber.state!==2)throw Error('Plugin '+fiber.name+' failed to activate after resolving its services');}
 }
}
