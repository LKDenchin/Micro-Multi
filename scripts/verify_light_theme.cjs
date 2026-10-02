const {app,BrowserWindow}=require('electron');
const fs=require('node:fs');const path=require('node:path');
app.disableHardwareAcceleration();
app.whenReady().then(async()=>{
 const w=new BrowserWindow({show:false,width:1100,height:820,webPreferences:{sandbox:true,backgroundThrottling:false}});
 try{
  await w.loadURL('http://127.0.0.1:8769/');await new Promise(r=>setTimeout(r,800));
  await w.webContents.executeJavaScript(`(()=>{
   document.body.classList.add('theme-light');document.body.classList.remove('theme-dark');
   const fixture=document.createElement('div');fixture.id='theme-fixture';
   fixture.style='position:fixed;inset:30px;z-index:9999;background:white;padding:20px;color:#222;overflow:auto';
   fixture.innerHTML='<h3>Light theme interaction regression</h3>'+['generic','inspector','left','dialog'].map((scope,i)=>{
    const cls=scope==='inspector'?'inspector':'';const id=scope==='left'?'left-tool-content':'';
    const tag=scope==='dialog'?'dialog':'div';
    return '<'+tag+' open class="'+cls+'" id="'+id+'" style="position:static;padding:12px;background:white"><button class="select-option" id="option-'+i+'">'+scope+' dropdown option</button></'+tag+'>';
   }).join('')+'<div class="review-model-select-wrap"><button class="select-trigger" id="review-trigger">Review model</button><div class="select-popover" id="review-popover" style="position:static">Review model dropdown</div></div><div class="turn-deliverable-card"><span class="turn-deliverable-icon">File</span><div class="turn-deliverable-info"><strong>test</strong></div><button class="turn-deliverable-open" id="deliverable-button">View changes</button></div><div class="turn-edits-card"><div class="turn-edits-head"><span class="turn-edits-title" id="edits-title">3 edited files</span><button class="turn-edits-btn" id="edits-button">Review</button></div><div class="turn-edits-row">index.html</div></div><div class="tool-step-detail plain-output" id="raw-output">{"written":"test/styles.css","bytes":9999,"diff":"readable output"}</div>';
   document.body.append(fixture);
  })()`);
  const checks=[];
  const assertColor=async(selector,property,expected)=>{
   const actual=await w.webContents.executeJavaScript(`getComputedStyle(document.querySelector(${JSON.stringify(selector)}))[${JSON.stringify(property)}]`);
   if(actual!==expected){const debug=await w.webContents.executeJavaScript(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});return {html:e.outerHTML,parent:e.parentElement.outerHTML,body:document.body.className,hover:e.matches(':hover'),focus:e.matches(':focus-visible'),rect:e.getBoundingClientRect().toJSON()}})()`);console.error(debug);throw Error(selector+' '+property+' '+actual+' expected '+expected);}
   checks.push(selector+' '+property+' '+expected);
  };
  w.webContents.debugger.attach('1.3');await w.webContents.debugger.sendCommand('DOM.enable');await w.webContents.debugger.sendCommand('CSS.enable');
  const {root}=await w.webContents.debugger.sendCommand('DOM.getDocument');
  for(let i=0;i<4;i++){
   const selector='#option-'+i;
   await assertColor(selector,'color','rgb(37, 37, 37)');
   const {nodeId}=await w.webContents.debugger.sendCommand('DOM.querySelector',{nodeId:root.nodeId,selector});
   for(const pseudoClass of ['hover','focus-visible']){
    await w.webContents.debugger.sendCommand('CSS.forcePseudoState',{nodeId,forcedPseudoClasses:[pseudoClass]});
    await assertColor(selector,'backgroundColor','rgb(239, 239, 239)');await assertColor(selector,'color','rgb(17, 17, 17)');
   }
   await w.webContents.debugger.sendCommand('CSS.forcePseudoState',{nodeId,forcedPseudoClasses:[]});
   await w.webContents.executeJavaScript(`document.querySelector('${selector}').setAttribute('aria-selected','true')`);
   await assertColor(selector,'backgroundColor','rgb(229, 229, 229)');
  }
  await assertColor('#review-popover','backgroundColor','rgb(255, 255, 255)');await assertColor('#review-trigger','backgroundColor','rgb(255, 255, 255)');await assertColor('#review-trigger','color','rgb(37, 37, 37)');
  await assertColor('#raw-output','backgroundColor','rgb(247, 247, 247)');await assertColor('#raw-output','color','rgb(37, 37, 37)');
  await assertColor('#edits-title','color','rgb(51, 51, 51)');
  for(const selector of ['#deliverable-button','#edits-button']){
   await assertColor(selector,'backgroundColor','rgb(242, 242, 242)');
   const {nodeId}=await w.webContents.debugger.sendCommand('DOM.querySelector',{nodeId:root.nodeId,selector});
   await w.webContents.debugger.sendCommand('CSS.forcePseudoState',{nodeId,forcedPseudoClasses:['hover']});
   await assertColor(selector,'backgroundColor','rgb(229, 229, 229)');
  }
  await new Promise(r=>setTimeout(r,250));await w.webContents.capturePage();await new Promise(r=>setTimeout(r,150));
  fs.mkdirSync('evidence/ui-regression',{recursive:true});fs.writeFileSync('evidence/ui-regression/light-controls.png',(await w.webContents.capturePage()).toPNG());
  await w.webContents.executeJavaScript("document.body.classList.remove('theme-light')");
  await assertColor('#raw-output','backgroundColor','rgb(14, 14, 14)');
  console.log(JSON.stringify({passed:checks.length,checks},null,2));app.exit(0);
 }catch(e){console.error(e.stack);app.exit(1);}
});
