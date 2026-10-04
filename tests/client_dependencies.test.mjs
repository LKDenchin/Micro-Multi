import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync,readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createRequire} from 'node:module';
import {ClientDependencies} from '../src/masp/native/client_dependencies.mjs';
import {clientSource} from '../src/masp/native/client_source.mjs';
const root=mkdtempSync(join(tmpdir(),'micro-multi-dependencies-'));
try{
 const library=join(root,'library');mkdirSync(library);
 writeFileSync(join(library,'package.json'),JSON.stringify({name:'unseen-library-fixture',version:'1.0.0',type:'module',exports:{'.':'./index.js','./client':'./index.js'}}));
 writeFileSync(join(library,'index.js'),'export const value=42;');
 const plugin=join(root,'plugin');mkdirSync(plugin);writeFileSync(join(plugin,'package.json'),JSON.stringify({name:'unseen-plugin-fixture',devDependencies:{'unseen-library-fixture':'file:'+library}}));
 const require=createRequire(join(plugin,'package.json')),resolver=new ClientDependencies(join(root,'cache'),createRequire(import.meta.url));
 const path=resolver.ensure('unseen-library-fixture',require,resolver.owner(join(plugin,'client.js')));
 assert.equal(JSON.parse(readFileSync(path,'utf8')).version,'1.0.0');
 assert.equal((await import(pathToFileURL(resolver.resolve('unseen-library-fixture',require,{})))).value,42);
 assert.equal(resolver.ensure('unseen-library-fixture',require),path);
 const syntax=clientSource(`// require('invented-module')
 window.__ModuleLoader__.load({id:'fixture',factory:n=>{const message="require('another-invented-module')";const actual=n('real-library');return {apply(ctx){ctx.slots.inject('settings.example',()=>ctx.slots.register({name:'settings.section',children:{'settings.example.child':{kind:'list'}}},()=>null));}};}});`);
 assert.deepEqual(syntax.imports,['real-library']);assert.deepEqual(syntax.slots,['settings.example']);assert.deepEqual(syntax.children,['settings.example.child']);
 console.log('PASS: undeclared production library provisioned from package metadata, hidden package.json export, cached reuse, syntax-based client graph');
}finally{rmSync(root,{recursive:true,force:true});}
