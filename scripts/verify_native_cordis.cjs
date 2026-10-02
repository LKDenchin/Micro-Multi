const {app,BrowserWindow}=require('electron');
const fs=require('node:fs');const path=require('node:path');
app.whenReady().then(async()=>{
 const probe=path.resolve('src/masp/web/chat_native_probe.js');
 fs.writeFileSync(probe,fs.readFileSync('src/masp/web/chat.js','utf8')+'\nwindow.nativeProbe={applyLocale,loadPlugins};');
 const win=new BrowserWindow({show:false,webPreferences:{sandbox:true}});
 win.webContents.session.webRequest.onBeforeRequest({urls:['http://127.0.0.1:8769/static/chat.js*']},(_d,cb)=>cb({redirectURL:'http://127.0.0.1:8769/static/chat_native_probe.js'}));
 try{
 await win.loadURL('http://127.0.0.1:8769/');
 const results=await win.webContents.executeJavaScript(`(async()=>{
 const checks=[];const assert=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 const wait=async(predicate)=>{for(let i=0;i<100;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,50));}throw Error('UI timed out');};
 await wait(()=>document.querySelector('#settings-install-plugin-path'));
 await fetch('/api/dsh/bundles/bundle-micro-multi-native-example',{method:'DELETE'});
 await nativeProbe.loadPlugins();
 document.querySelector('#settings-install-plugin-path').value=${JSON.stringify(path.resolve('examples/native-cordis'))};
 document.querySelector('#settings-install-plugin-btn').click();
 await wait(async()=>{
  const inventory=await(await fetch('/api/dsh/plugins')).json();
  return inventory.bundles.some(b=>b.id==='bundle-micro-multi-native-example')&&inventory.tool_plugins.some(t=>t.native_tool==='native_counter');
 });
 await wait(()=>document.querySelector('.native-runtime-label'));
 assert(document.querySelector('.native-runtime-label').textContent.includes('原生 Cordis'),'Native bundle loads through settings button');
 const inventory=await(await fetch('/api/dsh/plugins')).json();const bundle=inventory.bundles.find(b=>b.id==='bundle-micro-multi-native-example');
 assert(bundle&&inventory.tool_plugins.some(t=>t.native_tool==='native_counter'),'Real native tool added to inventory');
 nativeProbe.applyLocale('en-US');await new Promise(r=>setTimeout(r,50));
 assert(document.querySelector('.native-runtime-label').textContent==='Native Cordis Host · 4.0.4','Native runtime label translated');
 document.querySelector('[data-dsh-toggle="'+bundle.id+'"]').click();
 await wait(async()=>!(await(await fetch('/api/dsh/plugins')).json()).bundles.find(b=>b.id===bundle.id).enabled);
 assert(!(await(await fetch('/api/dsh/plugins')).json()).tool_plugins.find(t=>t.native_tool==='native_counter').enabled,'Parent disabled state applies to native tool');
 await new Promise(r=>setTimeout(r,100));document.querySelector('[data-dsh-delete-bundle="'+bundle.id+'"]').click();
 await wait(async()=>!(await(await fetch('/api/dsh/plugins')).json()).bundles.some(b=>b.id===bundle.id));
 assert(!(await(await fetch('/api/dsh/plugins')).json()).tool_plugins.some(t=>t.native_tool==='native_counter'),'Native bundle removal prunes tool inventory');
 return checks;
 })()`);
 console.log(JSON.stringify({passed:results.length,checks:results},null,2));
 fs.unlinkSync(probe);app.exit(0);
 }catch(error){console.error(error);fs.unlinkSync(probe);app.exit(1);}
});
