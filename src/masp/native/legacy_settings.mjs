/** Preserve the published DSH namespace protocol alongside Config forms. */
import LegacySettings from './vendor/dsh-settings-namespace/index.mjs';
import {readFile,mkdir,writeFile,rename,unlink} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
class NamespaceSettings extends LegacySettings {
 writable=true;
 constructor(ctx,{home}){super(ctx);this.path=resolve(home,'native-namespace-settings.json');this.saved={};this.tail=Promise.resolve();}
 async load(){
  // Carry forward namespaces stored by the earlier Config-entry bridge.
  try{const previous=JSON.parse(await readFile(resolve(dirname(this.path),'native-bundle-settings.json'),'utf8'));this.saved=Object.fromEntries(Object.values(previous).flatMap(sections=>Object.entries(sections)));}catch(error){if(error.code!=='ENOENT')throw error;}
  try{this.saved={...this.saved,...JSON.parse(await readFile(this.path,'utf8'))};}catch(error){if(error.code!=='ENOENT')throw error;}
  return this.saved;
 }
 persist(ns,section){const work=this.tail.then(async()=>{const next={...this.saved,[ns]:section};await mkdir(dirname(this.path),{recursive:true});const temp=this.path+'.'+randomUUID()+'.tmp';try{await writeFile(temp,JSON.stringify(next),{mode:0o600});await rename(temp,this.path);}finally{await unlink(temp).catch(error=>{if(error.code!=='ENOENT')throw error;});}this.saved=next;});this.tail=work.catch(()=>{});return work;}
}
export async function installNamespaceSettings(root,home){
 // A minimal native profile may not contain the Config forms provider.
 if(!root.get('settings'))return new Map();
 const label=Symbol('native-namespace-settings'),scope=root.isolate('settings',label);
 await scope.plugin(NamespaceSettings,{home});
 const native=root.settings,owners=new Map();
 native.register=function(ns,schema,options){
  const caller=this.ctx.isolate('settings',label),legacy=caller.reflect.get('settings');
  const handle=legacy.register(ns,schema,options);
  owners.set(ns,this.ctx.fiber);
  this.ctx.effect(()=>()=>{owners.delete(ns);native.invalidate();});native.invalidate();return handle;
 };
 native.get=function(ns){return scope.settings.get(ns)??root.configEditor.entries().find(entry=>entry.options.id===ns)?.fiber?.config;};
 const describe=native.describe.bind(native);
 native.describe=options=>{const rows=scope.settings.describe(options);return [...describe(options).filter(row=>!rows.some(other=>other.ns===row.ns)),...rows];};
 for(const method of ['update','replace','mutate']){const original=native[method].bind(native);native[method]=function(ns,...args){return scope.settings.registrations.has(ns)?scope.settings[method](ns,...args):original(ns,...args);};}
 root.on('settings/updated',(ns)=>{root.emit('settings/document-updated',ns);native.invalidate();});
 return owners;
}
