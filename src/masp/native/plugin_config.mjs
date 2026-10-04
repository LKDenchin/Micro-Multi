/** Native settings editor for application-managed bundles, with atomic durable overrides. */
import {Service} from '@deepseek-ai/cordis';
import {readFile,mkdir,writeFile,rename,unlink} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
export default class BundleConfigEditor extends Service{
 constructor(ctx,{home,name='configEditor'}){super(ctx,name);this.rows=new Map();this.overrides={};this.tail=Promise.resolve();this.documentPath=resolve(home,'native-bundle-settings.json');}
 async load(){try{this.overrides=JSON.parse(await readFile(this.documentPath,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}}
 configFor(bundleId,id,base){return this.overrides[bundleId]?.[id]??base;}
 register(bundleId,id,fiber,base){
  if(this.entries().some(entry=>entry.options.id===id))throw Error('Ambiguous native settings namespace: '+id);
  const entry={id:bundleId+':'+id,bundleId,fiber,base,options:{id,name:fiber.name,config:fiber.config}};this.rows.set(entry.id,entry);
  this.ctx.settings?.invalidate();
  return ()=>{this.rows.delete(entry.id);this.ctx.settings?.invalidate();};
 }
 entries(){return [...this.rows.values()];}
 configuration(){return this.entries().map(entry=>({entry,inherited:entry.base,override:this.overrides[entry.bundleId]?.[entry.options.id]??{}}));}
 async updateFiber(fiber,config){
  let updateTask;const uid=fiber.uid;
  const off=this.ctx.on('internal/update',function(_config,_noSave,next){if(this.uid!==uid)return next();updateTask=Promise.resolve().then(next);return updateTask;},{global:true,prepend:true});
  try{fiber.update(config,true);await updateTask;await fiber;}finally{off();}
 }
 edit(entry,change){
  const work=this.tail.then(async()=>{
   if(this.rows.get(entry.id)!==entry)throw Error('Plugin settings entry was unloaded');
   const next=change(structuredClone(entry.options.config),structuredClone(entry.base));
   // Validate before persisting or restarting a plugin.
   const schema=entry.fiber.runtime?.Config;schema?.(next);
   const overrides={...this.overrides,[entry.bundleId]:{...this.overrides[entry.bundleId],[entry.options.id]:next}};
   const previous=entry.options.config;
   try{
    await this.updateFiber(entry.fiber,next);entry.options.config=next;
    await mkdir(dirname(this.documentPath),{recursive:true});const temporary=this.documentPath+'.'+randomUUID()+'.tmp';
    try{await writeFile(temporary,JSON.stringify(overrides),{encoding:'utf8',mode:0o600});await rename(temporary,this.documentPath);}finally{await unlink(temporary).catch(error=>{if(error.code!=='ENOENT')throw error;});}
    this.overrides=overrides;
   }catch(error){entry.options.config=previous;await this.updateFiber(entry.fiber,previous);throw error;}
   this.ctx.emit('app-boot/config-reload');
  });this.tail=work.catch(()=>{});return work;
 }
}
