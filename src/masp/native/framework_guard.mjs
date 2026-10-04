/** Keep the application SDK independent of plugins that rewrite installed files. */
import {createRequire,registerHooks} from 'node:module';
import {readFileSync,readdirSync,mkdirSync,existsSync,writeFileSync,renameSync} from 'node:fs';
import {dirname,resolve,relative,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {gunzipSync} from 'node:zlib';

const require=createRequire(import.meta.url);
const scope=dirname(dirname(require.resolve('@deepseek-ai/cordis/package.json')));
const lock=resolve(scope,'../../package-lock.json');
const locked=JSON.parse(readFileSync(lock,'utf8')).packages;
const packages=readdirSync(scope).sort().flatMap(name=>{
 const metadata=join(scope,name,'package.json');if(!existsSync(metadata))return [];
 const version=JSON.parse(readFileSync(metadata,'utf8')).version,entry=locked['node_modules/@deepseek-ai/'+name];
 if(!entry?.integrity||entry.version!==version)throw Error('Framework package does not match lockfile: '+name);
 return [{name,version,integrity:entry.integrity,resolved:entry.resolved}];
});
// Adding an unrelated plugin dependency must not reset the trusted SDK baseline.
const identity=Buffer.from(JSON.stringify(packages));
const key=createHash('sha256').update(identity).digest('hex');
const bundled=resolve(dirname(fileURLToPath(import.meta.url)),'../../../../framework-source',key);
const cache=existsSync(join(bundled,'complete.json'))?bundled:resolve(scope,'../.micro-multi-framework',key);
const marker=join(cache,'complete.json');
const provenance=join(cache,'verified-packages.json');
let trusted=false;
try{const verified=JSON.parse(readFileSync(provenance,'utf8'));trusted=JSON.stringify(verified.packages)===JSON.stringify(packages)&&Object.entries(verified.sources).every(([name,digest])=>createHash('sha256').update(readFileSync(join(cache,name))).digest('hex')===digest)&&JSON.parse(readFileSync(marker,'utf8')).every(name=>verified.sources[name]);}catch{}
if(!trusted){
 mkdirSync(cache,{recursive:true});const records=[];
 let cursor=0;
 await Promise.all(Array.from({length:12},async()=>{
  while(cursor<packages.length){
   const pkg=packages[cursor++],archive=resolve(scope,'../../.research',`deepseek-ai-${pkg.name}-${pkg.version}.tgz`);
   let bytes=existsSync(archive)?readFileSync(archive):null;
   const verified=value=>pkg.integrity.split(/\s+/).some(sri=>{const dash=sri.indexOf('-');return createHash(sri.slice(0,dash)).update(value).digest('base64')===sri.slice(dash+1);});
   if(!bytes||!verified(bytes)){const response=await fetch(pkg.resolved,{signal:AbortSignal.timeout(30000)});if(!response.ok)throw Error('Cannot acquire locked framework archive: '+pkg.name);bytes=Buffer.from(await response.arrayBuffer());}
   if(!verified(bytes))throw Error('Framework archive integrity mismatch: '+pkg.name);
   const tar=gunzipSync(bytes);
   for(let offset=0;offset+512<=tar.length;){
    const header=tar.subarray(offset,offset+512),name=header.subarray(0,100).toString().replace(/\0.*$/s,''),size=parseInt(header.subarray(124,136).toString().replace(/\0.*$/s,'').trim()||'0',8);
    if(!name)break;if(!Number.isFinite(size)||size<0)throw Error('Invalid framework archive: '+pkg.name);
    const body=tar.subarray(offset+512,offset+512+size);offset+=512+Math.ceil(size/512)*512;
    if(!name.startsWith('package/')||!/[.]([cm]?js)$/.test(name))continue;
    const target=resolve(cache,pkg.name,name.slice(8));if(!target.startsWith(resolve(cache,pkg.name)+'/')&&!target.startsWith(resolve(cache,pkg.name)+'\\'))throw Error('Invalid framework archive path');
    mkdirSync(dirname(target),{recursive:true});const temporary=target+'.'+randomUUID()+'.tmp';writeFileSync(temporary,body);renameSync(temporary,target);records.push(relative(cache,target));
   }
  }
 }));
 const hashes=Object.fromEntries(records.map(name=>[name,createHash('sha256').update(readFileSync(join(cache,name))).digest('hex')]));
 const proof=provenance+'.'+randomUUID()+'.tmp';writeFileSync(proof,JSON.stringify({packages,sources:hashes}));renameSync(proof,provenance);
 const temporary=marker+'.'+randomUUID()+'.tmp';writeFileSync(temporary,JSON.stringify(records));renameSync(temporary,marker);
}
const sources=new Map(JSON.parse(readFileSync(marker,'utf8')).map(name=>[resolve(scope,name),readFileSync(join(cache,name),'utf8')]));
export function frameworkSource(path){return sources.get(resolve(path));}
registerHooks({load(url,context,nextLoad){const result=nextLoad(url,context);if(!url.startsWith('file:'))return result;const source=frameworkSource(fileURLToPath(url));return source===undefined?result:{...result,source};}});
